//! Syntax observations, never a runtime dependency graph.
use super::*;

fn index_key(index: &Index) -> (String, Option<String>) {
    match index {
        Index::Dot { name, .. } => {
            let name = name.token().to_string();
            (name.clone(), Some(name))
        }
        Index::Brackets { expression, .. } => (
            expression.to_string().trim().to_owned(),
            literal_string(expression),
        ),
        _ => unreachable!("Lua 5.1"),
    }
}

// Decode only literal Lua 5.1 strings, without evaluating expressions. Decimal
// escapes forming non-UTF8 bytes cannot be represented as JSON names.
pub(super) fn literal_string(expr: &Expression) -> Option<String> {
    if let Expression::Parentheses { expression, .. } = expr {
        return literal_string(expression);
    }
    let Expression::String(token) = expr else {
        return None;
    };
    let raw = token.token().to_string();
    let value = if raw.starts_with('[') {
        let open = raw.find('[')? + 1;
        let second = raw[open..].find('[')? + open;
        let n = second + 1;
        let mut value = raw[n..raw.len() - n]
            .replace("\r\n", "\n")
            .replace('\r', "\n");
        if value.starts_with('\n') {
            value.remove(0);
        }
        value
    } else {
        let mut bytes = Vec::new();
        let body = &raw.as_bytes()[1..raw.len() - 1];
        let mut i = 0;
        while i < body.len() {
            if body[i] != b'\\' {
                bytes.push(body[i]);
                i += 1;
                continue;
            }
            i += 1;
            let ch = *body.get(i)?;
            if ch.is_ascii_digit() {
                let mut value = 0u16;
                let mut count = 0;
                while i < body.len() && body[i].is_ascii_digit() && count < 3 {
                    value = value * 10 + (body[i] - b'0') as u16;
                    i += 1;
                    count += 1;
                }
                bytes.push(u8::try_from(value).ok()?);
                continue;
            }
            bytes.push(match ch {
                b'a' => 7,
                b'b' => 8,
                b'f' => 12,
                b'n' => 10,
                b'r' => 13,
                b't' => 9,
                b'v' => 11,
                b'\r' | b'\n' => 10,
                other => other,
            });
            if ch == b'\r' && body.get(i + 1) == Some(&b'\n') {
                i += 1;
            }
            i += 1;
        }
        String::from_utf8(bytes).ok()?
    };
    (!value.is_empty()).then_some(value)
}

impl Extractor<'_> {
    fn call_binding(&self, expression: &str) -> Binding {
        if let Some(binding) = self.lookup(expression) {
            return binding;
        }
        if let Some((receiver, name)) = expression.rsplit_once('.') {
            if let Some(Binding::Class { id, .. } | Binding::Instance { id, .. }) =
                self.lookup(receiver)
            {
                return self
                    .methods
                    .get(&(id, name.to_owned()))
                    .cloned()
                    .unwrap_or(Binding::Other);
            }
        }
        Binding::Other
    }

    fn component_read(&mut self, receiver: &str, index: &Index, span: (usize, usize), write: bool) {
        let (expression, literal) = index_key(index);
        let key = (span.0, span.1, "component_access".to_owned());
        if !self.observed_accesses.insert(key) {
            return;
        }
        if write {
            self.diagnostic("direct-component-write", "Direct component slot write is not AddComponent/RemoveComponent or a read; inspect assignment. No operation guessed.", Some(span));
            return;
        }
        let evidence = self
            .condition_spans
            .iter()
            .copied()
            .filter(|(a, b)| *a <= span.0 && span.1 <= *b)
            .min_by_key(|(a, b)| b - a)
            .unwrap_or(span);
        self.record("component_access", self.subject(), evidence, json!({"receiver":receiver,"name_expression":expression,"literal_name":literal,"operation":"read"}));
        // The evidence may include the entire if condition, while execution of
        // this access still depends on its own short-circuit RHS location.
        let guards = self.json_guards(span);
        self.records.last_mut().unwrap()["guards"] = json!(guards);
    }

    pub(super) fn observe_chain(&mut self, prefix: &Prefix, suffixes: Vec<&Suffix>, write: bool) {
        let start = range(prefix).0;
        let mut expression = self.text(prefix);
        let mut chain_binding = match prefix {
            Prefix::Name(name) => self
                .lookup(&name.token().to_string())
                .unwrap_or(Binding::Other),
            Prefix::Expression(expr) => self.expression_binding(expr),
            _ => Binding::Other,
        };
        let mut components_receiver: Option<String> = None;
        for (index, suffix) in suffixes.iter().enumerate() {
            let end = match suffix {
                Suffix::Index(Index::Brackets { brackets, .. }) => {
                    brackets.tokens().1.token().end_position().bytes()
                }
                _ => range(*suffix).1,
            };
            let span = (start, end);
            match suffix {
                Suffix::Index(key) => {
                    if let Some(receiver) = components_receiver.take() {
                        self.component_read(
                            &receiver,
                            key,
                            span,
                            write && index + 1 == suffixes.len(),
                        );
                    }
                    let (_, literal) = index_key(key);
                    chain_binding = match (&chain_binding, &literal) {
                        (Binding::Class { id, .. } | Binding::Instance { id, .. }, Some(name)) => {
                            self.methods
                                .get(&(id.clone(), name.clone()))
                                .cloned()
                                .unwrap_or(Binding::Other)
                        }
                        _ => Binding::Other,
                    };
                    if literal.as_deref() == Some("components") {
                        components_receiver = Some(expression.clone());
                    }
                    expression = self.source[start..end].to_owned();
                }
                Suffix::Call(call) => {
                    components_receiver = None;
                    let (receiver, callee, args) = match call {
                        Call::MethodCall(method) => (
                            Some(expression.clone()),
                            method.name().token().to_string(),
                            method.args(),
                        ),
                        Call::AnonymousCall(args) => (None, expression.clone(), args.as_ref()),
                        _ => unreachable!("Lua 5.1"),
                    };
                    let arguments: Vec<String> = match args {
                        FunctionArgs::Parentheses { arguments, .. } => {
                            arguments.iter().map(|arg| self.text(arg)).collect()
                        }
                        FunctionArgs::String(string) => vec![self.text(string)],
                        FunctionArgs::TableConstructor(table) => vec![self.text(table)],
                        _ => unreachable!("Lua 5.1"),
                    };
                    let binding_expression = receiver
                        .as_ref()
                        .map_or(callee.clone(), |receiver| format!("{receiver}.{callee}"));
                    let binding = if receiver.is_none() {
                        chain_binding.clone()
                    } else {
                        match &chain_binding {
                            Binding::Class { id, .. } | Binding::Instance { id, .. } => self
                                .methods
                                .get(&(id.clone(), callee.clone()))
                                .cloned()
                                .unwrap_or(Binding::Other),
                            _ => self.call_binding(&binding_expression),
                        }
                    };
                    let record_index = self.records.len();
                    self.record("call",self.subject(),span,json!({"receiver":receiver,"callee":callee,"arguments":arguments,"resolution":resolution(&binding)}));
                    // A method body can mention a method declared later in the same
                    // class. Resolve only this known instance, using final conservative
                    // member bindings. This is a source link, not execution proof.
                    if let Some(receiver) = &receiver {
                        if let Some(Binding::Instance { id, .. }) = self.lookup(receiver) {
                            self.deferred_calls.push((record_index, id, callee.clone()));
                        }
                    }
                    let literal = arguments.first().and_then(|_| match args {
                        FunctionArgs::Parentheses { arguments, .. } => {
                            arguments.iter().next().and_then(literal_string)
                        }
                        FunctionArgs::String(string) => {
                            literal_string(&Expression::String(string.clone()))
                        }
                        _ => None,
                    });
                    if let Some(receiver) = receiver.as_ref() {
                        if let Some(name) = arguments.first() {
                            match callee.as_str() {
                                "PushEvent" | "ListenForEvent" => {
                                    let emit = callee == "PushEvent";
                                    self.record(if emit {"event_emit"}else{"event_listen"},self.subject(),span,json!({"receiver":receiver,"name_expression":name,"literal_name":literal,
                                        "payload_expression":if emit {arguments.get(1)}else{None},"callback_expression":if emit {None}else{arguments.get(1)}}));
                                }
                                "AddComponent" | "RemoveComponent" => {
                                    self.record("component_access",self.subject(),span,json!({"receiver":receiver,"name_expression":name,"literal_name":literal,"operation":if callee=="AddComponent"{"add"}else{"remove"}}));
                                }
                                _ => {}
                            }
                        }
                    } else if callee == "Prefab" && self.lookup("Prefab").is_none() {
                        if arguments.len() >= 2 {
                            let factory_binding = match args {
                                FunctionArgs::Parentheses { arguments, .. } => arguments
                                    .iter()
                                    .nth(1)
                                    .map_or(Binding::Other, |arg| self.expression_binding(arg)),
                                _ => Binding::Other,
                            };
                            self.record("prefab_registration",self.subject(),span,json!({"name_expression":arguments[0],"literal_name":literal,"factory_expression":arguments[1],"resolution":resolution(&factory_binding)}));
                        } else {
                            self.diagnostic(
                                "incomplete-prefab-call",
                                "Prefab call lacks explicit name/factory; ordinary call retained.",
                                Some(span),
                            );
                        }
                    }
                    expression = self.source[start..end].to_owned();
                    chain_binding = Binding::Other;
                }
                _ => unreachable!("Lua 5.1"),
            }
        }
    }
    pub(super) fn finish_relations(&mut self) {
        for (index, class, name) in &self.deferred_calls {
            let binding = self
                .methods
                .get(&(class.clone(), name.clone()))
                .cloned()
                .unwrap_or(Binding::Other);
            self.records[*index]["data"]["resolution"] = resolution(&binding);
        }
    }
}
