//! Structural declarations, writes, properties, aliases and lexical guards.
mod guards;
mod relations;
use full_moon::{
    ast::*,
    node::Node,
    tokenizer::{Token, TokenType},
    visitors::Visitor,
    LuaVersion,
};
use guards::Guards;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};

pub fn valid_path(path: &str) -> bool {
    !path.is_empty()
        && path.ends_with(".lua")
        && !path.contains(['\\', ':'])
        && path
            .split('/')
            .all(|part| !part.is_empty() && part != "." && part != "..")
}

fn range(node: &impl Node) -> (usize, usize) {
    let (start, end) = node.range().expect("parsed node has a byte range");
    (start.bytes(), end.bytes())
}

fn parameters(body: &FunctionBody) -> Vec<Value> {
    body.parameters()
        .iter()
        .map(|parameter| match parameter {
            Parameter::Name(name) => json!({"name":name.token().to_string(),"kind":"named"}),
            Parameter::Ellipsis(_) => json!({"name":"...","kind":"vararg"}),
            _ => unreachable!("fixed Lua 5.1 parser"),
        })
        .collect()
}

#[derive(Clone)]
enum Binding {
    Other,
    Class { id: String, scope: String },
    Function(String),
    PendingFunction(usize),
    Candidates(Vec<String>),
    Instance { id: String, scope: String },
}
struct Frame {
    scope: String,
    bindings: HashMap<String, Binding>,
    block_count: usize,
}
struct FunctionContext {
    id: String,
    scope: String,
    parameters: Vec<String>,
    colon: bool,
    instance: Option<(String, String, String)>,
}
#[derive(Clone)]
struct Hint {
    name: String,
    kind: &'static str,
    scope: String,
    owner: Option<String>,
    span: (usize, usize),
}

struct Extractor<'a> {
    source: &'a str,
    path: &'a str,
    anchors: BTreeMap<(usize, usize), Value>,
    symbols: Vec<Value>,
    records: Vec<Value>,
    diagnostics: Vec<Value>,
    frames: Vec<Frame>,
    functions: Vec<FunctionContext>,
    function_ranges: Vec<(usize, usize, String)>,
    hints: HashMap<usize, Hint>,
    pending_bindings: HashMap<usize, Vec<(String, Binding, bool)>>,
    counts: HashMap<String, usize>,
    anonymous: HashMap<String, usize>,
    next_function_block: bool,
    loop_bindings: HashMap<usize, Vec<String>>,
    guarded: Vec<(usize, usize)>,
    guards: Guards<'a>,
    fields: HashMap<(String, String), String>,
    methods: HashMap<(String, String), Binding>,
    pending_properties: HashMap<String, Vec<(String, String, (usize, usize), Binding)>>,
    pending_member_writes: HashMap<usize, Vec<(String, String, Binding)>>,
    inline_functions: HashMap<usize, String>,
    record_serial: usize,
    deferred_calls: Vec<(usize, String, String)>,
    observed_accesses: std::collections::HashSet<(usize, usize, String)>,
    assignment_targets: std::collections::HashSet<(usize, usize)>,
    condition_spans: Vec<(usize, usize)>,
    line_starts: Vec<usize>,
}

impl<'a> Extractor<'a> {
    fn new(source: &'a str, path: &'a str, guards: Guards<'a>) -> Self {
        Self {
            source,
            path,
            anchors: BTreeMap::new(),
            symbols: vec![],
            records: vec![],
            diagnostics: vec![],
            frames: vec![],
            functions: vec![],
            function_ranges: vec![],
            hints: HashMap::new(),
            pending_bindings: HashMap::new(),
            counts: HashMap::new(),
            anonymous: HashMap::new(),
            next_function_block: false,
            loop_bindings: HashMap::new(),
            guarded: vec![],
            guards,
            fields: HashMap::new(),
            methods: HashMap::new(),
            pending_properties: HashMap::new(),
            pending_member_writes: HashMap::new(),
            inline_functions: HashMap::new(),
            record_serial: 0,
            deferred_calls: vec![],
            observed_accesses: Default::default(),
            assignment_targets: Default::default(),
            condition_spans: vec![],
            line_starts: std::iter::once(0)
                .chain(
                    source
                        .bytes()
                        .enumerate()
                        .filter_map(|(i, b)| (b == b'\n').then_some(i + 1)),
                )
                .collect(),
        }
    }
    fn text(&self, node: &impl Node) -> String {
        let (start, end) = range(node);
        self.source[start..end].to_owned()
    }
    fn position(&self, byte: usize) -> Value {
        let line = self.line_starts.partition_point(|start| *start <= byte);
        json!({"byte":byte,"line":line,"column":byte-self.line_starts[line-1]+1})
    }
    fn anchor(&mut self, span: (usize, usize)) -> String {
        let (start, end) = span;
        if let Some(anchor) = self.anchors.get(&span) {
            return anchor["id"].as_str().unwrap().to_owned();
        }
        let id = format!("facts:{}:{start}:{end}", self.path);
        self.anchors.insert(
            span,
            json!({"id":id,"source_id":"dst","path":self.path,
            "start":self.position(start),"end":self.position(end),
            "sha256":format!("{:x}",Sha256::digest(&self.source.as_bytes()[start..end]))}),
        );
        id
    }
    fn diagnostic(&mut self, code: &str, message: &str, span: Option<(usize, usize)>) {
        let anchor = span.map(|span| self.anchor(span));
        self.diagnostics
            .push(json!({"code":code,"severity":"warning","message":message,"anchor_id":anchor}));
    }
    fn scope(&self) -> String {
        self.frames
            .last()
            .map_or("module".to_owned(), |frame| frame.scope.clone())
    }
    fn owner(&self) -> Option<String> {
        self.functions.last().map(|function| function.id.clone())
    }
    fn lookup(&self, name: &str) -> Option<Binding> {
        self.frames
            .iter()
            .rev()
            .find_map(|frame| frame.bindings.get(name).cloned())
    }
    fn bind(&mut self, name: String, value: Binding, local: bool) {
        let index = if local {
            self.frames.len() - 1
        } else {
            self.frames
                .iter()
                .rposition(|frame| frame.bindings.contains_key(&name))
                .unwrap_or(0)
        };
        // Uncalled closure/branch writes cannot establish a unique outer runtime
        // binding. Preserve known alternatives or invalidate an unknown value.
        let uncertain_write =
            !local
                && (self.functions.last().is_some_and(|function| {
                    !self.frames[index].scope.starts_with(&function.scope)
                }) || self
                    .frames
                    .last()
                    .is_some_and(|frame| frame.scope.contains("/block:")));
        let value = if uncertain_write {
            let previous = self.frames[index]
                .bindings
                .get(&name)
                .cloned()
                .unwrap_or(Binding::Other);
            merge_bindings(previous, value)
        } else {
            value
        };
        self.frames[index].bindings.insert(name, value);
    }
    fn subject(&self) -> String {
        self.owner()
            .unwrap_or_else(|| format!("{}#module/function:<chunk>", self.path))
    }
    fn json_guards(&mut self, span: (usize, usize)) -> Vec<Value> {
        self.guards
            .at(span)
            .into_iter()
            .map(|guard| {
                let anchor = self.anchor(guard.evidence);
                json!({"expression":guard.expression,"branch":guard.branch,"anchor_id":anchor})
            })
            .collect()
    }
    fn record(&mut self, kind: &str, subject: String, span: (usize, usize), data: Value) {
        self.record_serial += 1;
        let id = format!("{}#record:{}", self.path, self.record_serial);
        let anchor = self.anchor(span);
        let guards = self.json_guards(span);
        self.records.push(json!({"id":id,"kind":kind,"subject_symbol_id":subject,"anchor_id":anchor,"guards":guards,"data":data}));
    }
    fn field(&mut self, class: &str, scope: &str, name: &str, span: (usize, usize)) -> String {
        let key = (class.to_owned(), name.to_owned());
        if let Some(id) = self.fields.get(&key) {
            return id.clone();
        }
        let id = self.symbol(
            &Hint {
                name: name.to_owned(),
                kind: "field",
                scope: scope.to_owned(),
                owner: Some(class.to_owned()),
                span,
            },
            vec![],
            "none",
            None,
        );
        self.fields.insert(key, id.clone());
        id
    }
    fn expression_binding(&self, expression: &Expression) -> Binding {
        match expression {
            Expression::Var(var) => {
                let Some(names) = target_names(var) else {
                    return Binding::Other;
                };
                if names.len() == 1 {
                    return self.lookup(&names[0]).unwrap_or(Binding::Other);
                }
                let receiver = names[..names.len() - 1].join(".");
                if let Some(Binding::Class { id, .. }) = self.lookup(&receiver) {
                    return self
                        .methods
                        .get(&(id, names.last().unwrap().clone()))
                        .cloned()
                        .unwrap_or(Binding::Other);
                }
                Binding::Other
            }
            Expression::Parentheses { expression, .. } => self.expression_binding(expression),
            Expression::Function(function) => self
                .inline_functions
                .get(&range(function).0)
                .map_or(Binding::Other, |id| Binding::Function(id.clone())),
            _ => Binding::Other,
        }
    }
    fn method_binding(
        &mut self,
        class: String,
        name: String,
        value: Binding,
        span: (usize, usize),
    ) {
        let key = (class, name);
        let conditional = !self.guards.at(span).is_empty() || !self.functions.is_empty();
        let binding = if conditional {
            merge_bindings(
                self.methods.get(&key).cloned().unwrap_or(Binding::Other),
                value,
            )
        } else {
            value
        };
        self.methods.insert(key, binding);
    }
    fn symbol(
        &mut self,
        hint: &Hint,
        parameters: Vec<Value>,
        calling: &str,
        base: Option<String>,
    ) -> String {
        let stem = format!("{}#{}/{}:{}", self.path, hint.scope, hint.kind, hint.name);
        let count = self.counts.entry(stem.clone()).or_default();
        *count += 1;
        let id = if *count == 1 {
            stem
        } else {
            format!("{stem}@{count}")
        };
        if *count > 1 {
            self.diagnostic(
                "repeated-definition",
                "Repeated name retained as a separate definition; no target chosen.",
                Some(hint.span),
            );
        }
        if let Some(span) = self
            .guarded
            .iter()
            .copied()
            .find(|(start, end)| *start <= hint.span.0 && hint.span.1 <= *end)
        {
            self.diagnostic("conditional-symbol",
                "Symbol is declared inside a conditional/loop region. Inspect its containing source and associated assignment/property records; symbols alone do not encode guards.",Some(span));
        }
        let anchor = self.anchor(hint.span);
        self.symbols.push(json!({"id":id,"kind":hint.kind,"name":hint.name,"scope":hint.scope,
            "owner_id":hint.owner,"anchor_id":anchor,"parameters":parameters,"calling":calling,"base_expression":base}));
        id
    }
    fn enter_function(&mut self, hint: Hint, body: &FunctionBody, calling: &str) -> String {
        let params = parameters(body);
        let id = self.symbol(&hint, params.clone(), calling, None);
        let instance = if hint.kind == "constructor" || calling == "colon" && hint.owner.is_some() {
            hint.owner.clone().map(|class| {
                let name = if calling == "colon" {
                    "self".to_owned()
                } else {
                    params
                        .first()
                        .and_then(|p| p["name"].as_str())
                        .unwrap_or("self")
                        .to_owned()
                };
                (name, class, hint.scope.clone())
            })
        } else {
            None
        };
        let suffix = id
            .strip_prefix(&format!("{}#{}/{}:", self.path, hint.scope, hint.kind))
            .unwrap();
        let child_scope = format!("{}/{}", hint.scope, suffix);
        self.function_ranges
            .push((hint.span.0, hint.span.1, id.clone()));
        self.functions.push(FunctionContext {
            id: id.clone(),
            scope: child_scope,
            parameters: params
                .iter()
                .filter_map(|p| {
                    p["name"]
                        .as_str()
                        .filter(|s| *s != "...")
                        .map(str::to_owned)
                })
                .collect(),
            colon: calling == "colon",
            instance,
        });
        id
    }
    fn receiver_hint(
        &mut self,
        names: Vec<String>,
        method: Option<String>,
        span: (usize, usize),
    ) -> Hint {
        if names.len() == 1 && method.is_none() {
            return Hint {
                name: names[0].clone(),
                kind: "function",
                scope: self.scope(),
                owner: self.owner(),
                span,
            };
        }
        let (name, receiver) = match method {
            Some(method) => (method, names.join(".")),
            None => (
                names.last().unwrap().clone(),
                names[..names.len() - 1].join("."),
            ),
        };
        if let Some(Binding::Class { id, scope }) = self.lookup(&receiver) {
            Hint {
                name,
                kind: "method",
                scope,
                owner: Some(id),
                span,
            }
        } else {
            self.diagnostic(
                "unresolved-method-owner",
                "Receiver is not a unique visible Class binding; ownership remains unknown.",
                Some(span),
            );
            let scope = if self.scope() == "module" {
                receiver
            } else {
                format!("{}/{}", self.scope(), receiver)
            };
            Hint {
                name,
                kind: "method",
                scope,
                owner: None,
                span,
            }
        }
    }
    fn assignment(
        &mut self,
        span: (usize, usize),
        targets: Vec<Option<Vec<String>>>,
        expressions: Vec<&Expression>,
        target_texts: Vec<String>,
        local: bool,
    ) {
        let mut bindings = vec![];
        for (index, target) in targets.iter().enumerate() {
            if let Some(expression) = expressions.get(index) {
                self.record(
                    "assignment",
                    self.subject(),
                    span,
                    json!({"target":target_texts[index],
                    "expression":self.text(*expression),"literal_kind":literal_kind(expression)}),
                );
            } else {
                let expanding = expressions
                    .last()
                    .is_some_and(|expression| is_expanding(expression));
                self.diagnostic(if expanding {"expanded-assignment-deferred"} else {"implicit-assignment-value-deferred"},
                    "Written target has no independent RHS expression; no synthetic value expression emitted.",Some(span));
            }
            let Some(names) = target else { continue };
            if names.len() == 2 {
                if let Some(Binding::Instance { id, scope }) = self.lookup(&names[0]) {
                    self.field(&id, &scope, &names[1], span);
                }
            }
            let mut binding = Binding::Other;
            if let Some(expression) = expressions.get(index) {
                match expression {
                    Expression::Function(function) => {
                        let receiver = names[..names.len() - 1].join(".");
                        let hint = if names.len() > 1
                            && !matches!(self.lookup(&receiver), Some(Binding::Class { .. }))
                        {
                            // An instance/table callback assignment is not a class method.
                            // Retain its written target name and lexical owner until field facts exist.
                            self.diagnostic("unresolved-function-assignment-owner",
                                "Function assignment target is retained as its lexical name; no class/field ownership inferred.",Some(range(function)));
                            Hint {
                                name: names.join("."),
                                kind: "function",
                                scope: self.scope(),
                                owner: self.owner(),
                                span: range(function),
                            }
                        } else {
                            self.receiver_hint(names.clone(), None, range(function))
                        };
                        self.hints.insert(range(function).0, hint);
                        binding = Binding::PendingFunction(range(function).0);
                    }
                    Expression::FunctionCall(call) if names.len() == 1 => {
                        if let Prefix::Name(prefix) = call.prefix() {
                            let suffixes: Vec<_> = call.suffixes().collect();
                            if prefix.token().to_string() == "Class" && suffixes.len() == 1 {
                                if self.lookup("Class").is_some() {
                                    self.diagnostic("shadowed-class","Class is locally defined or overwritten; call is not classified as DST Class.",Some(range(call)));
                                } else if let Suffix::Call(Call::AnonymousCall(args)) = suffixes[0]
                                {
                                    if let FunctionArgs::Parentheses { arguments, .. } =
                                        args.as_ref()
                                    {
                                        let args: Vec<_> = arguments.iter().collect();
                                        // Only classify overloads whose constructor position is syntactically known.
                                        let first_is_ctor=args.len()==1 || args.get(1).is_some_and(|e|
                                            matches!(e,Expression::Symbol(t) if t.token().to_string()=="nil"));
                                        let ctor = match args.as_slice() {
                                            [Expression::Function(function), ..]
                                                if first_is_ctor =>
                                            {
                                                Some((function.as_ref(), Some("nil".to_owned())))
                                            }
                                            [base, Expression::Function(function), ..] => {
                                                Some((function.as_ref(), Some(self.text(*base))))
                                            }
                                            _ => None,
                                        };
                                        if let Some((constructor, base)) = ctor {
                                            let hint = Hint {
                                                name: names[0].clone(),
                                                kind: "class",
                                                scope: self.scope(),
                                                owner: self.owner(),
                                                span,
                                            };
                                            let id = self.symbol(&hint, vec![], "none", base);
                                            let class_name = id
                                                .strip_prefix(&format!(
                                                    "{}#{}/class:",
                                                    self.path, hint.scope
                                                ))
                                                .unwrap();
                                            let scope = if self.scope() == "module" {
                                                class_name.to_owned()
                                            } else {
                                                format!("{}/{}", self.scope(), class_name)
                                            };
                                            self.hints.insert(
                                                range(constructor).0,
                                                Hint {
                                                    name: "new".to_owned(),
                                                    kind: "constructor",
                                                    scope: scope.clone(),
                                                    owner: Some(id.clone()),
                                                    span: range(constructor),
                                                },
                                            );
                                            if let Some(Expression::TableConstructor(properties)) =
                                                args.get(2)
                                            {
                                                let mut entries = vec![];
                                                for field in properties.fields().iter() {
                                                    let property = match field {
                                                        Field::NameKey { key, value, .. } => {
                                                            Some((key.token().to_string(), value))
                                                        }
                                                        Field::ExpressionKey {
                                                            key, value, ..
                                                        } => relations::literal_string(key)
                                                            .map(|key| (key, value)),
                                                        _ => None,
                                                    };
                                                    if let Some((key, value)) = property {
                                                        let binding =
                                                            if let Expression::Function(function) =
                                                                value.as_ref()
                                                            {
                                                                Binding::PendingFunction(
                                                                    range(function).0,
                                                                )
                                                            } else {
                                                                self.expression_binding(value)
                                                            };
                                                        entries.push((
                                                            key,
                                                            self.text(value.as_ref()),
                                                            range(field),
                                                            binding,
                                                        ));
                                                    } else {
                                                        self.diagnostic("dynamic-property-key-deferred","Class property key is not a literal name; mapping retained in source, not inferred.",Some(range(field)));
                                                    }
                                                }
                                                self.pending_properties.insert(id.clone(), entries);
                                            } else if args.len() > 2 {
                                                self.diagnostic("dynamic-properties-deferred","Class properties expression is not an inline table; mapping needs later resolution.",Some(range(call)));
                                            }
                                            binding = Binding::Class { id, scope };
                                        } else {
                                            self.diagnostic("unresolved-class-overload","Class constructor/base expressions need later resolution; no class ownership inferred.",Some(range(call)));
                                        }
                                    }
                                }
                            }
                        }
                    }
                    _ => {}
                }
                if matches!(binding, Binding::Other)
                    && !matches!(expression, Expression::Function(_))
                {
                    binding = self.expression_binding(expression);
                }
                if names.len() == 2 {
                    if let Some(Binding::Class { id, scope }) = self.lookup(&names[0]) {
                        if !matches!(expression, Expression::Function(_))
                            && matches!(binding, Binding::Function(_) | Binding::Candidates(_))
                        {
                            let (params, calling) = match &binding {
                                Binding::Function(target) => self
                                    .symbols
                                    .iter()
                                    .find(|s| s["id"] == *target)
                                    .map(|s| {
                                        (
                                            s["parameters"].as_array().unwrap().clone(),
                                            s["calling"].as_str().unwrap().to_owned(),
                                        )
                                    })
                                    .unwrap_or((vec![], "none".to_owned())),
                                _ => (vec![], "none".to_owned()),
                            };
                            let target = self.symbol(
                                &Hint {
                                    name: names[1].clone(),
                                    kind: "method",
                                    scope,
                                    owner: Some(id.clone()),
                                    span,
                                },
                                params,
                                &calling,
                                None,
                            );
                            self.record("method_alias",id.clone(),span,json!({"target_symbol_id":target,"expression":self.text(*expression),"resolution":resolution(&binding)}));
                        } else if matches!(
                            expression,
                            Expression::Var(_) | Expression::Parentheses { .. }
                        ) {
                            self.diagnostic("unknown-member-assignment","Class member RHS is not a known function; assignment retained without inventing a method alias.",Some(span));
                        }
                        self.pending_member_writes.entry(span.0).or_default().push((
                            id,
                            names[1].clone(),
                            binding.clone(),
                        ));
                    }
                }
            }
            if names.len() == 1 {
                bindings.push((names[0].clone(), binding, local));
            }
        }
        self.pending_bindings.insert(span.0, bindings);
    }
    fn finish_assignment(&mut self, span: (usize, usize)) {
        for (class, name, binding) in self
            .pending_member_writes
            .remove(&span.0)
            .unwrap_or_default()
        {
            let binding = self.finish_binding(binding);
            self.method_binding(class, name, binding, span);
        }
        for (name, value, local) in self.pending_bindings.remove(&span.0).unwrap_or_default() {
            let value = self.finish_binding(value);
            if let Binding::Class { id, scope } = &value {
                for (name, expression, evidence, binding) in
                    self.pending_properties.remove(id).unwrap_or_default()
                {
                    let field = self.field(id, scope, &name, evidence);
                    let binding = self.finish_binding(binding);
                    self.record("property_callback",id.clone(),evidence,json!({"field_symbol_id":field,"callback_expression":expression,"resolution":resolution(&binding)}));
                }
            }
            self.bind(name, value, local)
        }
    }
    fn finish_binding(&self, binding: Binding) -> Binding {
        if let Binding::PendingFunction(byte) = binding {
            self.inline_functions
                .get(&byte)
                .map_or(Binding::Other, |id| Binding::Function(id.clone()))
        } else {
            binding
        }
    }
    fn comments(&mut self, ast: &Ast) {
        let mut visitor = EvidenceVisitor {
            source: self.source,
            valid: true,
            comments: BTreeMap::new(),
        };
        visitor.visit_ast(ast);
        for token in visitor.comments.values() {
            let span = (token.start_position().bytes(), token.end_position().bytes());
            let subject = self
                .function_ranges
                .iter()
                .filter(|(start, end, _)| *start <= span.0 && span.1 <= *end)
                .min_by_key(|(start, end, _)| end - start)
                .map_or_else(
                    || format!("{}#module/function:<chunk>", self.path),
                    |(_, _, id)| id.clone(),
                );
            let style = if matches!(token.token_type(), TokenType::SingleLineComment { .. }) {
                "line"
            } else {
                "block"
            };
            self.record(
                "comment",
                subject,
                span,
                json!({"text":self.source[span.0..span.1],"style":style}),
            );
        }
    }
}

fn target_names(var: &Var) -> Option<Vec<String>> {
    match var {
        Var::Name(name) => Some(vec![name.token().to_string()]),
        Var::Expression(expression) => {
            let Prefix::Name(name) = expression.prefix() else {
                return None;
            };
            let mut names = vec![name.token().to_string()];
            for suffix in expression.suffixes() {
                match suffix {
                    Suffix::Index(Index::Dot { name, .. }) => names.push(name.token().to_string()),
                    Suffix::Index(Index::Brackets { expression, .. }) => {
                        names.push(relations::literal_string(expression)?)
                    }
                    _ => return None,
                }
            }
            Some(names)
        }
        _ => None,
    }
}

fn function_ids(binding: &Binding) -> Vec<String> {
    match binding {
        Binding::Function(id) => vec![id.clone()],
        Binding::Candidates(ids) => ids.clone(),
        _ => vec![],
    }
}
fn merge_bindings(first: Binding, second: Binding) -> Binding {
    let first_ids = function_ids(&first);
    let second_ids = function_ids(&second);
    if first_ids.is_empty() || second_ids.is_empty() {
        return Binding::Other;
    }
    let mut ids = first_ids;
    ids.extend(second_ids);
    ids.sort();
    ids.dedup();
    if ids.len() == 1 {
        Binding::Function(ids.remove(0))
    } else {
        Binding::Candidates(ids)
    }
}
fn resolution(binding: &Binding) -> Value {
    match binding {
        Binding::Function(id) => {
            json!({"state":"resolved","symbol_id":id,"candidates":[],"reason":null})
        }
        Binding::Candidates(ids) => {
            json!({"state":"ambiguous","symbol_id":null,"candidates":ids,"reason":"Conditional/closure writes leave multiple structurally possible definitions; unique runtime target not proven."})
        }
        _ => {
            json!({"state":"unresolved","symbol_id":null,"candidates":[],"reason":"No unique visible function definition for this expression; dynamic, overwritten or external target."})
        }
    }
}
fn literal_kind(expression: &Expression) -> &'static str {
    match expression {
        Expression::Number(_) => "number",
        Expression::String(_) => "string",
        Expression::TableConstructor(_) => "table",
        Expression::Function(_) => "function",
        Expression::Symbol(token) if token.token().to_string() == "nil" => "nil",
        Expression::Symbol(token)
            if matches!(token.token().to_string().as_str(), "true" | "false") =>
        {
            "boolean"
        }
        _ => "nonliteral",
    }
}
fn is_expanding(expression: &Expression) -> bool {
    matches!(expression, Expression::FunctionCall(_))
        || matches!(expression,Expression::Symbol(token) if token.token().to_string()=="...")
}

impl Visitor for Extractor<'_> {
    fn visit_block(&mut self, node: &Block) {
        let mut bindings = HashMap::new();
        let scope = if self.next_function_block {
            self.next_function_block = false;
            let function = self.functions.last().unwrap();
            for name in &function.parameters {
                bindings.insert(name.clone(), Binding::Other);
            }
            if function.colon {
                bindings.insert("self".to_owned(), Binding::Other);
            }
            if let Some((name, id, scope)) = &function.instance {
                bindings.insert(
                    name.clone(),
                    Binding::Instance {
                        id: id.clone(),
                        scope: scope.clone(),
                    },
                );
            }
            function.scope.clone()
        } else if let Some(parent) = self.frames.last_mut() {
            parent.block_count += 1;
            format!("{}/block:{}", parent.scope, parent.block_count)
        } else {
            "module".to_owned()
        };
        for name in self
            .loop_bindings
            .remove(&(node as *const Block as usize))
            .unwrap_or_default()
        {
            bindings.insert(name, Binding::Other);
        }
        self.frames.push(Frame {
            scope,
            bindings,
            block_count: 0,
        });
    }
    fn visit_block_end(&mut self, _: &Block) {
        self.frames.pop();
    }
    fn visit_function_body(&mut self, _: &FunctionBody) {
        self.next_function_block = true;
    }
    fn visit_local_function(&mut self, node: &LocalFunction) {
        let name = node.name().token().to_string();
        let hint = Hint {
            name: name.clone(),
            kind: "function",
            scope: self.scope(),
            owner: self.owner(),
            span: range(node),
        };
        let subject = self.subject();
        let id = self.enter_function(hint, node.body(), "plain");
        self.bind(name, Binding::Function(id), true);
        if !self.guards.at(range(node)).is_empty() {
            self.record("assignment",subject,range(node),json!({"target":node.name().token().to_string(),"expression":self.text(node),"literal_kind":"function"}));
        }
    }
    fn visit_local_function_end(&mut self, _: &LocalFunction) {
        self.functions.pop();
    }
    fn visit_function_declaration(&mut self, node: &FunctionDeclaration) {
        let names: Vec<_> = node
            .name()
            .names()
            .iter()
            .map(|n| n.token().to_string())
            .collect();
        let method = node.name().method_name().map(|n| n.token().to_string());
        let calling = if method.is_some() { "colon" } else { "plain" };
        let hint = self.receiver_hint(names.clone(), method, range(node));
        let method_owner = if hint.kind == "method" {
            hint.owner.clone().map(|owner| (owner, hint.name.clone()))
        } else {
            None
        };
        let subject = self.subject();
        let id = self.enter_function(hint, node.body(), calling);
        if let Some((class, name)) = method_owner {
            let context = self.functions.pop().unwrap();
            self.method_binding(class, name, Binding::Function(id.clone()), range(node));
            self.functions.push(context);
        }
        if names.len() == 1 && calling == "plain" {
            let context = self.functions.pop().unwrap();
            self.bind(names[0].clone(), Binding::Function(id), false);
            self.functions.push(context);
        }
        // A condition-bearing declaration can be joined with its symbol by source
        // interval and original written target without adding v1 symbol fields.
        if !self.guards.at(range(node)).is_empty() {
            self.record("assignment",subject,range(node),json!({"target":self.text(node.name()),"expression":self.text(node),"literal_kind":"function"}));
        }
    }
    fn visit_function_declaration_end(&mut self, _: &FunctionDeclaration) {
        self.functions.pop();
    }
    fn visit_anonymous_function(&mut self, node: &AnonymousFunction) {
        let span = range(node);
        let hint = self.hints.remove(&span.0).unwrap_or_else(|| {
            let scope = self.scope();
            let count = self.anonymous.entry(scope.clone()).or_default();
            *count += 1;
            Hint {
                name: format!("anon:{count}"),
                kind: "function",
                scope,
                owner: self.owner(),
                span,
            }
        });
        let id = self.enter_function(hint, node.body(), "plain");
        self.inline_functions.insert(span.0, id);
    }
    fn visit_anonymous_function_end(&mut self, _: &AnonymousFunction) {
        self.functions.pop();
    }
    fn visit_local_assignment(&mut self, node: &LocalAssignment) {
        self.assignment(
            range(node),
            node.names()
                .iter()
                .map(|n| Some(vec![n.token().to_string()]))
                .collect(),
            node.expressions().iter().collect(),
            node.names()
                .iter()
                .map(|name| name.token().to_string())
                .collect(),
            true,
        );
    }
    fn visit_local_assignment_end(&mut self, node: &LocalAssignment) {
        self.finish_assignment(range(node));
    }
    fn visit_assignment(&mut self, node: &Assignment) {
        for var in node.variables().iter() {
            self.assignment_targets.insert(range(var));
        }
        self.assignment(
            range(node),
            node.variables().iter().map(target_names).collect(),
            node.expressions().iter().collect(),
            node.variables().iter().map(|var| self.text(var)).collect(),
            false,
        );
    }
    fn visit_assignment_end(&mut self, node: &Assignment) {
        self.finish_assignment(range(node));
    }
    fn visit_return(&mut self, node: &Return) {
        self.record("return",self.subject(),range(node),json!({"expressions":node.returns().iter().map(|expression|self.text(expression)).collect::<Vec<_>>(),"implicit":false}));
    }
    fn visit_function_call_end(&mut self, node: &FunctionCall) {
        self.observe_chain(node.prefix(), node.suffixes().collect(), false);
    }
    fn visit_var_expression_end(&mut self, node: &VarExpression) {
        self.observe_chain(
            node.prefix(),
            node.suffixes().collect(),
            self.assignment_targets.contains(&range(node)),
        );
    }
    fn visit_if(&mut self, node: &If) {
        self.guarded.push(range(node));
        self.condition_spans.push(range(node.condition()));
    }
    fn visit_while(&mut self, node: &While) {
        self.guarded.push(range(node));
        self.condition_spans.push(range(node.condition()));
    }
    fn visit_repeat(&mut self, node: &Repeat) {
        self.guarded.push(range(node));
    }
    fn visit_numeric_for(&mut self, node: &NumericFor) {
        self.guarded.push(range(node));
        self.loop_bindings.insert(
            node.block() as *const Block as usize,
            vec![node.index_variable().token().to_string()],
        );
    }
    fn visit_generic_for(&mut self, node: &GenericFor) {
        self.guarded.push(range(node));
        self.loop_bindings.insert(
            node.block() as *const Block as usize,
            node.names().iter().map(|n| n.token().to_string()).collect(),
        );
    }
}

fn failure(snapshot: &str, path: &str, code: &str, message: String) -> Value {
    json!({"format_version":"1.0.0","kind":"facts","snapshot_id":snapshot,"primary_file":path,
        "coverage":{"status":"failed","selection":{"symbols":[],"record_kinds":[],"description":"Declaration extraction rejected input."},
            "truncated":false,"diagnostics":[{"code":code,"severity":"error","message":message,"anchor_id":null}]},
        "anchors":[],"symbols":[],"records":[]})
}

fn check_token(source: &str, token: &Token) -> bool {
    source
        .get(token.start_position().bytes()..token.end_position().bytes())
        .is_some_and(|s| s == token.to_string())
}

// Full Moon's flattened Node::tokens iterator shifts a Vec per token and is
// quadratic for large literal tables. Visit references directly instead.
struct EvidenceVisitor<'a> {
    source: &'a str,
    valid: bool,
    comments: BTreeMap<usize, Token>,
}
impl Visitor for EvidenceVisitor<'_> {
    fn visit_token(&mut self, token: &Token) {
        self.valid &= check_token(self.source, token);
        if matches!(
            token.token_type(),
            TokenType::SingleLineComment { .. } | TokenType::MultiLineComment { .. }
        ) {
            self.comments
                .insert(token.start_position().bytes(), token.clone());
        }
    }
}

pub fn extract(snapshot: &str, path: &str, bytes: &[u8]) -> Value {
    if bytes.starts_with(b"\x1bLua") {
        return failure(
            snapshot,
            path,
            "lua-bytecode",
            "Compiled Lua chunk is unsupported; original bytes preserved.".to_owned(),
        );
    }
    let source = match std::str::from_utf8(bytes) {
        Ok(source) => source,
        Err(error) => return failure(snapshot, path, "non-utf8-source", error.to_string()),
    };
    let ast = match full_moon::parse_fallible(source, LuaVersion::lua51()).into_result() {
        Ok(ast) => ast,
        Err(errors) => {
            return failure(
                snapshot,
                path,
                "syntax-error",
                errors
                    .iter()
                    .map(|error| {
                        let (start, end) = error.range();
                        let byte = start.bytes().min(source.len());
                        let prefix = &source[..byte];
                        let line = prefix.bytes().filter(|b| *b == b'\n').count() + 1;
                        let column = prefix.rfind('\n').map_or(byte + 1, |i| byte - i);
                        let context = source.lines().nth(line - 1).unwrap_or("<EOF>");
                        // Bounded diagnostic context; never expose a repaired AST as evidence.
                        let context: String = context.chars().take(160).collect();
                        format!(
                            "{path}:{line}:{column}, bytes {}..{}: {}; context: {context}",
                            start.bytes(),
                            end.bytes(),
                            error.error_message()
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("; "),
            );
        }
    };
    let mut evidence = EvidenceVisitor {
        source,
        valid: true,
        comments: BTreeMap::new(),
    };
    evidence.visit_ast(&ast);
    if ast.to_string() != source || !evidence.valid {
        return failure(
            snapshot,
            path,
            "invalid-source-evidence",
            "AST/token bytes differ from original input.".to_owned(),
        );
    }
    let mut extractor = Extractor::new(source, path, Guards::collect(source, &ast));
    extractor.symbol(
        &Hint {
            name: "<chunk>".to_owned(),
            kind: "function",
            scope: "module".to_owned(),
            owner: None,
            span: (0, bytes.len()),
        },
        vec![],
        "plain",
        None,
    );
    extractor.visit_ast(&ast);
    extractor.comments(&ast);
    extractor.finish_relations();
    let partial = extractor.diagnostics.iter().any(|d| {
        let code = d["code"].as_str().unwrap();
        code.contains("deferred")
            || matches!(code, "unresolved-class-overload" | "direct-component-write")
    });
    extractor.diagnostic("structural-analysis-limits","Selection covers explicit syntax observations and literal names with finite lexical resolution. It excludes implicit values/returns, short-circuit execution, full CFG, cross-file targets and runtime side effects; unresolved calls retain expressions. Complete is only for this syntax selection, not semantic completeness.",None);
    extractor.diagnostics.last_mut().unwrap()["severity"] = json!("info");
    json!({"format_version":"1.0.0","kind":"facts","snapshot_id":snapshot,"primary_file":path,
        "coverage":{"status":if partial {"partial"}else{"complete"},"selection":{"symbols":extractor.symbols.iter().map(|s|s["id"].clone()).collect::<Vec<_>>(),
            "record_kinds":["assignment","property_callback","method_alias","return","comment","call","event_emit","event_listen","component_access","prefab_registration"],"description":"Lua 5.1 declarations/writes/Class maps/aliases/guards/returns/trivia/calls/events/components/Prefab syntax; finite lexical resolution, no runtime graph."},
            "truncated":false,"diagnostics":extractor.diagnostics},
        "anchors":extractor.anchors.into_values().collect::<Vec<_>>(),"symbols":extractor.symbols,"records":extractor.records})
}
