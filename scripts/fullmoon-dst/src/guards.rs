//! Lexical guards within one executable function/chunk. No runtime CFG inference.
use full_moon::{ast::*, node::Node, visitors::Visitor};
use std::collections::HashMap;

pub type Span = (usize, usize);
pub fn span(node: &impl Node) -> Span {
    let (start, end) = node.range().expect("parsed node range");
    (start.bytes(), end.bytes())
}

#[derive(Clone, Debug)]
pub struct Guard {
    pub expression: String,
    pub branch: &'static str,
    pub evidence: Span,
}
struct Region {
    span: Span,
    context: Span,
    guard: Guard,
}
pub struct Guards<'a> {
    source: &'a str,
    regions: Vec<Region>,
    contexts: Vec<Span>,
    stack: Vec<Span>,
    block_ends: HashMap<usize, usize>,
}

fn always_returns(block: &Block) -> bool {
    fn may_break(block: &Block) -> bool {
        if matches!(block.last_stmt(), Some(LastStmt::Break(_))) {
            return true;
        }
        block.stmts().any(|stmt| match stmt {
            Stmt::Do(node) => may_break(node.block()),
            Stmt::If(node) => {
                may_break(node.block())
                    || node.else_block().is_some_and(may_break)
                    || node.else_if().is_some_and(|branches| {
                        branches.iter().any(|branch| may_break(branch.block()))
                    })
            }
            // A nested loop consumes its own break; function bodies execute separately.
            _ => false,
        })
    }
    if may_break(block) {
        return false;
    }
    if matches!(block.last_stmt(), Some(LastStmt::Return(_))) {
        return true;
    }
    match block.stmts().last() {
        Some(Stmt::Do(node)) => always_returns(node.block()),
        Some(Stmt::If(node)) => {
            node.else_block().is_some_and(always_returns)
                && always_returns(node.block())
                && node.else_if().is_none_or(|branches| {
                    branches.iter().all(|branch| always_returns(branch.block()))
                })
        }
        _ => false,
    }
}

impl<'a> Guards<'a> {
    pub fn collect(source: &'a str, ast: &Ast) -> Self {
        let root = (0, source.len());
        let mut visitor = Self {
            source,
            regions: vec![],
            contexts: vec![root],
            stack: vec![root],
            block_ends: HashMap::new(),
        };
        visitor
            .block_ends
            .insert(ast.nodes() as *const Block as usize, source.len());
        visitor.visit_ast(ast);
        visitor
    }
    fn text(&self, span: Span) -> String {
        self.source[span.0..span.1].to_owned()
    }
    fn condition(&self, expr: &Expression, branch: &'static str) -> Guard {
        let evidence = span(expr);
        Guard {
            expression: self.text(evidence),
            branch,
            evidence,
        }
    }
    fn region(&mut self, start: usize, end: usize, guard: Guard) {
        self.regions.push(Region {
            span: (start, end),
            context: *self.stack.last().unwrap(),
            guard,
        });
    }
    fn function(&mut self, node: &impl Node) {
        let context = span(node);
        self.contexts.push(context);
        self.stack.push(context);
    }
    pub fn at(&self, target: Span) -> Vec<Guard> {
        let context = *self
            .contexts
            .iter()
            .filter(|(start, end)| {
                *start <= target.0
                    && target.1 <= *end
                    && ((*start, *end) != target || (*start, *end) == (0, self.source.len()))
            })
            .min_by_key(|(start, end)| end - start)
            .unwrap();
        let mut regions: Vec<_> = self
            .regions
            .iter()
            .filter(|region| {
                region.context == context && region.span.0 <= target.0 && target.1 <= region.span.1
            })
            .collect();
        // Parent conditions precede nested conditions. For equal regions preserve
        // insertion order, which stores rejected elseif conditions before the branch.
        regions.sort_by_key(|region| (region.span.0, std::cmp::Reverse(region.span.1)));
        regions
            .into_iter()
            .map(|region| region.guard.clone())
            .collect()
    }
}

impl Visitor for Guards<'_> {
    fn visit_expression(&mut self, node: &Expression) {
        if let Expression::BinaryOperator { lhs, binop, rhs } = node {
            let operator = binop.to_string();
            let branch = match operator.trim() {
                "and" => "then",
                "or" => "else",
                _ => return,
            };
            let target = span(rhs.as_ref());
            self.region(target.0, target.1, self.condition(lhs, branch));
        }
    }
    fn visit_local_function(&mut self, node: &LocalFunction) {
        self.function(node);
    }
    fn visit_local_function_end(&mut self, _: &LocalFunction) {
        self.stack.pop();
    }
    fn visit_function_declaration(&mut self, node: &FunctionDeclaration) {
        self.function(node);
    }
    fn visit_function_declaration_end(&mut self, _: &FunctionDeclaration) {
        self.stack.pop();
    }
    fn visit_anonymous_function(&mut self, node: &AnonymousFunction) {
        self.function(node);
    }
    fn visit_anonymous_function_end(&mut self, _: &AnonymousFunction) {
        self.stack.pop();
    }
    fn visit_function_body(&mut self, node: &FunctionBody) {
        self.block_ends.insert(
            node.block() as *const Block as usize,
            node.end_token().token().start_position().bytes(),
        );
    }
    fn visit_block(&mut self, block: &Block) {
        let end = self
            .block_ends
            .get(&(block as *const Block as usize))
            .copied()
            .unwrap_or_else(|| span(block).1);
        for stmt in block.stmts() {
            if let Stmt::If(node) = stmt {
                if node.else_block().is_none()
                    && node.else_if().is_none()
                    && always_returns(node.block())
                {
                    self.region(
                        span(node).1,
                        end,
                        self.condition(node.condition(), "after-return"),
                    );
                }
                if node.else_block().is_none()
                    && node.else_if().is_some()
                    && always_returns(node.block())
                {
                    let branches = node.else_if().unwrap();
                    if branches.iter().all(|branch| always_returns(branch.block())) {
                        self.region(
                            span(node).1,
                            end,
                            self.condition(node.condition(), "after-return"),
                        );
                        for branch in branches {
                            self.region(
                                span(node).1,
                                end,
                                self.condition(branch.condition(), "after-return"),
                            );
                        }
                    }
                }
                if node.else_if().is_none() {
                    if let Some(other) = node.else_block() {
                        match (always_returns(node.block()), always_returns(other)) {
                            (true, false) => self.region(
                                span(node).1,
                                end,
                                self.condition(node.condition(), "after-return"),
                            ),
                            (false, true) => self.region(
                                span(node).1,
                                end,
                                self.condition(node.condition(), "then"),
                            ),
                            _ => {}
                        }
                    }
                }
            }
        }
    }
    fn visit_if(&mut self, node: &If) {
        let branches: Vec<_> = node
            .else_if()
            .map_or_else(Vec::new, |branches| branches.iter().collect());
        let last = node
            .else_token()
            .unwrap_or(node.end_token())
            .token()
            .start_position()
            .bytes();
        let first_end = branches.first().map_or(last, |branch| {
            branch.else_if_token().token().start_position().bytes()
        });
        self.block_ends
            .insert(node.block() as *const Block as usize, first_end);
        self.region(
            node.then_token().token().end_position().bytes(),
            first_end,
            self.condition(node.condition(), "then"),
        );
        let mut previous = vec![self.condition(node.condition(), "else")];
        for (index, branch) in branches.iter().enumerate() {
            let end = branches.get(index + 1).map_or(last, |next| {
                next.else_if_token().token().start_position().bytes()
            });
            let start = branch.then_token().token().end_position().bytes();
            self.block_ends
                .insert(branch.block() as *const Block as usize, end);
            for guard in &previous {
                self.region(start, end, guard.clone());
            }
            self.region(start, end, self.condition(branch.condition(), "elseif"));
            previous.push(self.condition(branch.condition(), "else"));
        }
        if let Some(block) = node.else_block() {
            let start = node.else_token().unwrap().token().end_position().bytes();
            let end = node.end_token().token().start_position().bytes();
            self.block_ends.insert(block as *const Block as usize, end);
            for guard in previous {
                self.region(start, end, guard);
            }
        }
    }
    fn visit_do(&mut self, node: &Do) {
        self.block_ends.insert(
            node.block() as *const Block as usize,
            node.end_token().token().start_position().bytes(),
        );
    }
    fn visit_while(&mut self, node: &While) {
        let end = node.end_token().token().start_position().bytes();
        self.block_ends
            .insert(node.block() as *const Block as usize, end);
        self.region(
            node.do_token().token().end_position().bytes(),
            end,
            self.condition(node.condition(), "loop"),
        );
    }
    fn visit_repeat(&mut self, node: &Repeat) {
        let end = node.until_token().token().start_position().bytes();
        self.block_ends
            .insert(node.block() as *const Block as usize, end);
        self.region(
            node.repeat_token().token().end_position().bytes(),
            end,
            self.condition(node.until(), "loop"),
        );
    }
    fn visit_numeric_for(&mut self, node: &NumericFor) {
        let end = node.end_token().token().start_position().bytes();
        self.block_ends
            .insert(node.block() as *const Block as usize, end);
        let evidence = (
            node.for_token().token().end_position().bytes(),
            node.do_token().token().start_position().bytes(),
        );
        self.region(
            node.do_token().token().end_position().bytes(),
            end,
            Guard {
                expression: self.text(evidence),
                branch: "loop",
                evidence,
            },
        );
    }
    fn visit_generic_for(&mut self, node: &GenericFor) {
        let end = node.end_token().token().start_position().bytes();
        self.block_ends
            .insert(node.block() as *const Block as usize, end);
        let expressions: Vec<_> = node.expressions().iter().collect();
        let evidence = (span(expressions[0]).0, span(*expressions.last().unwrap()).1);
        self.region(
            node.do_token().token().end_position().bytes(),
            end,
            Guard {
                expression: self.text(evidence),
                branch: "loop",
                evidence,
            },
        );
    }
}
