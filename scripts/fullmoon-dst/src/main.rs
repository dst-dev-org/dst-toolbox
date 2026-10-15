use std::{env, fs, process::ExitCode};

fn main() -> ExitCode {
    let args: Vec<_> = env::args_os().skip(1).collect();
    if args.len() != 3 {
        eprintln!("usage: fullmoon-dst <snapshot-id> <source-relative.lua> <input-path>");
        return ExitCode::from(2);
    }
    let Some(snapshot) = args[0].to_str() else {
        return ExitCode::from(2);
    };
    let Some(path) = args[1].to_str() else {
        return ExitCode::from(2);
    };
    if !fullmoon_dst::valid_path(path) || snapshot.is_empty() {
        eprintln!("invalid snapshot or source-relative .lua path");
        return ExitCode::from(2);
    }
    let bytes = match fs::read(&args[2]) {
        Ok(bytes) => bytes,
        Err(error) => {
            eprintln!("input access error: {error}");
            return ExitCode::from(2);
        }
    };
    let facts = fullmoon_dst::extract(snapshot, path, &bytes);
    println!("{}", serde_json::to_string(&facts).expect("JSON facts"));
    if facts["coverage"]["status"] == "failed" {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}
