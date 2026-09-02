use std::env;
use std::fs::OpenOptions;
use std::io::Write;

fn log_level() -> String {
    env::var("TDB_BRIDGE_LOG_LEVEL")
        .unwrap_or_else(|_| "INFO".to_string())
        .trim()
        .to_ascii_uppercase()
}

pub fn debug_enabled() -> bool {
    log_level() == "DEBUG"
}

fn append_log_file(line: &str) {
    let path = match env::var("TDB_BRIDGE_LOG_FILE") {
        Ok(v) if !v.trim().is_empty() => v,
        _ => return,
    };
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = file.write_all(line.as_bytes());
    }
}

pub fn log_info(message: &str) {
    let line = format!("[INFO] {message}\n");
    eprint!("{line}");
    append_log_file(&line);
}

pub fn log_debug(message: &str) {
    if !debug_enabled() {
        return;
    }
    let line = format!("[DEBUG] {message}\n");
    eprint!("{line}");
    append_log_file(&line);
}
