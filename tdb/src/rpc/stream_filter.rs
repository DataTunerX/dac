//! Shared SQL fragments for matching `stream_id` either exactly or as a
//! dot-delimited namespace prefix.
//!
//! A stream id like `kb.customer.bmw` is the parent of
//! `kb.customer.bmw.sales`, but NOT of `kb.customer.bmw2` — the `.` is the
//! hierarchy delimiter. The prefix form enforces that boundary with
//! `starts_with(col, prefix || '.')` rather than `LIKE`, so the bound value is
//! treated literally (no `_`/`%` wildcard pitfalls).

/// Predicate matching scalar text column `col` against text param `$p`.
///
/// When `prefix` is false this is a plain equality; when true it also matches
/// dot-delimited descendants. The caller binds exactly one value (`$p`)
/// regardless of which form is used.
pub fn stream_scalar_match(col: &str, p: usize, prefix: bool) -> String {
    if prefix {
        format!("({col} = ${p} OR starts_with({col}, ${p} || '.'))")
    } else {
        format!("{col} = ${p}")
    }
}

/// Predicate matching scalar text column `col` against any element of the
/// text[] param `$p`. Mirrors [`stream_scalar_match`] for the array case used
/// by search (`stream_ids`).
pub fn stream_array_match(col: &str, p: usize, prefix: bool) -> String {
    if prefix {
        format!(
            "EXISTS (SELECT 1 FROM unnest(${p}::text[]) AS s(prefix) \
             WHERE {col} = s.prefix OR starts_with({col}, s.prefix || '.'))"
        )
    } else {
        format!("{col} = ANY(${p}::text[])")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scalar_exact_is_plain_equality() {
        assert_eq!(
            stream_scalar_match("fe.stream_id", 2, false),
            "fe.stream_id = $2"
        );
    }

    #[test]
    fn scalar_prefix_uses_dot_boundary() {
        assert_eq!(
            stream_scalar_match("fe.stream_id", 2, true),
            "(fe.stream_id = $2 OR starts_with(fe.stream_id, $2 || '.'))"
        );
    }

    #[test]
    fn array_exact_uses_any() {
        assert_eq!(
            stream_array_match("d.stream_id", 3, false),
            "d.stream_id = ANY($3::text[])"
        );
    }

    #[test]
    fn array_prefix_uses_unnest_with_dot_boundary() {
        assert_eq!(
            stream_array_match("d.stream_id", 3, true),
            "EXISTS (SELECT 1 FROM unnest($3::text[]) AS s(prefix) \
             WHERE d.stream_id = s.prefix OR starts_with(d.stream_id, s.prefix || '.'))"
        );
    }
}
