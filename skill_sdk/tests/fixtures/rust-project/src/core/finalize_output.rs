/// FinalizeOutput applies post-processing to the result.
///
/// hover: wraps the data with [final] ... [ok] markers.
pub fn finalize_output(data: &str) -> String {
    format!("[final] {} [ok]", data)
}
