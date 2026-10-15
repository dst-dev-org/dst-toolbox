//! Parser and position readiness checks, not W01 facts or an extractor.
use full_moon::node::Node;
use full_moon::tokenizer::Token;
use full_moon::{ast::Ast, Error, LuaVersion};
use std::env;
use std::fs;
use std::process::ExitCode;

fn parse_source(source: &str) -> Result<Ast, Vec<Error>> {
    // Discard recovered ASTs: phantom tokens are not valid source evidence.
    full_moon::parse_fallible(source, LuaVersion::lua51()).into_result()
}

fn source_text(bytes: Vec<u8>) -> Result<String, String> {
    if bytes.starts_with(b"\x1bLua") {
        return Err("compiled Lua bytecode is unsupported; original bytes preserved".to_owned());
    }
    String::from_utf8(bytes).map_err(|error| format!("non-UTF-8 source: {error}"))
}

fn byte_position(source: &str, byte: usize) -> Result<(usize, usize), String> {
    let prefix = source
        .get(..byte)
        .ok_or_else(|| format!("invalid UTF-8 byte boundary: {byte}"))?;
    let line = prefix.bytes().filter(|value| *value == b'\n').count() + 1;
    let column = match prefix.rfind('\n') {
        Some(newline) => byte - newline,
        None => byte + 1,
    };
    Ok((line, column))
}

fn check_token(source: &str, token: &Token) -> Result<usize, String> {
    let start = token.start_position();
    let end = token.end_position();
    let original = source
        .get(start.bytes()..end.bytes())
        .ok_or_else(|| "token range is not an original UTF-8 byte slice".to_owned())?;
    if original != token.to_string() {
        return Err("token bytes differ from the original source".to_owned());
    }
    let mut native_position_differences = 0;
    for position in [start, end] {
        let (line, column) = byte_position(source, position.bytes())?;
        // Native line/character conventions are not our evidence contract.
        // Derive both coordinates from original bytes, including trivia ends.
        if position.line() != line || position.character() != column {
            native_position_differences += 1;
        }
    }
    Ok(native_position_differences)
}

fn check_ast(source: &str, ast: &Ast) -> Result<(usize, usize), String> {
    if ast.to_string() != source {
        return Err("AST roundtrip changes original source bytes".to_owned());
    }
    let mut token_count = 0;
    let mut native_position_differences = 0;
    for reference in ast.nodes().tokens().chain(std::iter::once(ast.eof())) {
        for token in reference
            .leading_trivia()
            .chain(std::iter::once(reference.token()))
            .chain(reference.trailing_trivia())
        {
            native_position_differences += check_token(source, token)?;
            token_count += 1;
        }
    }
    Ok((token_count, native_position_differences))
}

fn main() -> ExitCode {
    let mut paths: Vec<_> = env::args_os().skip(1).collect();
    let syntax_only = paths.first().is_some_and(|value| value == "--syntax-only");
    if syntax_only {
        paths.remove(0);
    }
    if paths.is_empty() {
        eprintln!("usage: parser_probe [--syntax-only] <Lua file> [<Lua file> ...]");
        return ExitCode::from(2);
    }
    let mut exit_code = 0;
    for path in paths {
        let display = std::path::Path::new(&path).display().to_string();
        let source = match fs::read(&path)
            .map_err(|error| error.to_string())
            .and_then(source_text)
        {
            Ok(source) => source,
            Err(error) => {
                eprintln!("ERROR {display}: {error}");
                exit_code = 2;
                continue;
            }
        };
        match parse_source(&source) {
            Ok(_) if syntax_only => {
                println!("PARSE {display}: {} bytes; byte/position checks skipped", source.len());
            }
            Ok(ast) => match check_ast(&source, &ast) {
                Ok((tokens, differences)) => println!(
                    "PASS {display}: {} bytes, {tokens} tokens, exact roundtrip; {differences} native position differences normalized from bytes",
                    source.len()
                ),
                Err(error) => {
                    eprintln!("ERROR {display}: {error}");
                    exit_code = 2;
                }
            },
            Err(errors) => {
                if exit_code == 0 {
                    exit_code = 1;
                }
                eprintln!("REJECT {display}: {} parse errors; recovered AST discarded", errors.len());
                for error in errors {
                    let (start, _) = error.range();
                    eprintln!("  byte {}: {}", start.bytes(), error.error_message());
                }
            }
        }
    }
    ExitCode::from(exit_code)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_unicode_crlf_and_half_open_token_ranges() {
        let source = "-- 中文\r\nlocal label = \"耐久\"; local value = 1\r\nreturn value\r\n";
        let ast = parse_source(source).expect("valid Lua 5.1");
        let (tokens, differences) = check_ast(source, &ast).expect("original token evidence");
        assert!(tokens > 0);
        assert!(differences > 0, "native positions require byte normalization");
        let value_byte = source.find("value").unwrap();
        let line_start = source.find('\n').unwrap() + 1;
        assert_eq!(byte_position(source, value_byte).unwrap(), (2, value_byte - line_start + 1));
        assert!(byte_position(source, source.find('耐').unwrap() + 1).is_err());
        assert_eq!(byte_position(source, source.len()).unwrap(), (4, 1));
    }

    #[test]
    fn rejects_syntax_errors_without_exposing_recovered_ast() {
        let result = parse_source("local function broken(value\nreturn value\n");
        assert!(result.is_err());
        assert!(!result.unwrap_err().is_empty());
    }

    #[test]
    fn rejects_newer_dialect_syntax() {
        for source in [
            "goto target; ::target::",
            "local value = 1 // 2",
            "local value = 1 & 2",
            "local value <const> = 1",
            "local value: number = 1",
            "while true do continue end",
        ] {
            assert!(parse_source(source).is_err(), "unsupported dialect accepted: {source}");
        }
    }

    #[test]
    fn accepts_lua51_environment_calls_varargs_and_long_strings() {
        // Syntax only: this does not execute or infer types of any game API.
        let source = r#"
local function bind(...)
    local values = { ... }
    local fn = loadstring([=[return 1]=])
    setfenv(fn, getfenv(1))
    return fn, unpack(values), select('#', ...), bit.band(3, 1)
end
function Example:Invoke(...) return bind(...) end
"#;
        assert!(parse_source(source).is_ok());
    }

    #[test]
    fn distinguishes_bytecode_and_legacy_encoding_without_transcoding() {
        assert!(source_text(b"\x1bLua\x51\x00".to_vec())
            .unwrap_err()
            .contains("bytecode"));
        assert!(source_text(b"-- Copyright \xa9\nreturn 1".to_vec())
            .unwrap_err()
            .contains("non-UTF-8"));
    }
}
