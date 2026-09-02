use time::{Date, Duration, Month, OffsetDateTime, PrimitiveDateTime, Time, Weekday};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TimeGranularity {
    Day,
    Week,
    Month,
}

#[derive(Clone, Debug, PartialEq)]
pub struct NormalizedTime {
    pub text: String,
    pub resolved_start: OffsetDateTime,
    pub resolved_end: Option<OffsetDateTime>,
    pub granularity: TimeGranularity,
    pub confidence: f32,
    pub rule: &'static str,
}

/// Normalize common relative-time phrases against an anchor timestamp.
///
/// The resolver is deterministic and intentionally conservative:
/// - It returns `None` for unknown/ambiguous phrases.
/// - Week ranges are Monday..Sunday.
pub fn normalize_relative_time(text: &str, anchor: OffsetDateTime) -> Option<NormalizedTime> {
    let norm = normalized_text(text);
    if norm.is_empty() {
        return None;
    }

    let anchor_date = anchor.date();

    if norm == "today" {
        return Some(single_day(text, anchor_date, anchor, "today", 1.0));
    }
    if norm == "yesterday" {
        return Some(single_day(
            text,
            anchor_date - Duration::days(1),
            anchor,
            "yesterday",
            1.0,
        ));
    }
    if norm == "tomorrow" {
        return Some(single_day(
            text,
            anchor_date + Duration::days(1),
            anchor,
            "tomorrow",
            1.0,
        ));
    }

    if norm == "last week" {
        let (start, end) = week_bounds(anchor_date - Duration::weeks(1));
        return Some(range(
            text,
            day_start(start, anchor),
            day_end(end, anchor),
            TimeGranularity::Week,
            1.0,
            "last_week",
        ));
    }
    if norm == "this week" {
        let (start, end) = week_bounds(anchor_date);
        return Some(range(
            text,
            day_start(start, anchor),
            day_end(end, anchor),
            TimeGranularity::Week,
            1.0,
            "this_week",
        ));
    }
    if norm == "next week" {
        let (start, end) = week_bounds(anchor_date + Duration::weeks(1));
        return Some(range(
            text,
            day_start(start, anchor),
            day_end(end, anchor),
            TimeGranularity::Week,
            1.0,
            "next_week",
        ));
    }

    if norm == "last month" {
        let month_date = shift_month(anchor_date, -1)?;
        let (start, end) = month_bounds(month_date)?;
        return Some(range(
            text,
            day_start(start, anchor),
            day_end(end, anchor),
            TimeGranularity::Month,
            1.0,
            "last_month",
        ));
    }
    if norm == "this month" {
        let (start, end) = month_bounds(anchor_date)?;
        return Some(range(
            text,
            day_start(start, anchor),
            day_end(end, anchor),
            TimeGranularity::Month,
            1.0,
            "this_month",
        ));
    }
    if norm == "next month" {
        let month_date = shift_month(anchor_date, 1)?;
        let (start, end) = month_bounds(month_date)?;
        return Some(range(
            text,
            day_start(start, anchor),
            day_end(end, anchor),
            TimeGranularity::Month,
            1.0,
            "next_month",
        ));
    }

    if let Some(weekday) = extract_last_next_weekday(&norm, "last") {
        let date = previous_weekday(anchor_date, weekday);
        return Some(single_day(text, date, anchor, "last_weekday", 0.95));
    }
    if let Some(weekday) = extract_last_next_weekday(&norm, "next") {
        let date = next_weekday(anchor_date, weekday);
        return Some(single_day(text, date, anchor, "next_weekday", 0.95));
    }

    if let Some((n, unit)) = extract_in_n_unit(&norm) {
        let date = shift_by_unit(anchor_date, n as i64, unit)?;
        return Some(single_day(text, date, anchor, "in_n_unit", 0.9));
    }
    if let Some((n, unit)) = extract_n_unit_ago(&norm) {
        let date = shift_by_unit(anchor_date, -(n as i64), unit)?;
        return Some(single_day(text, date, anchor, "n_unit_ago", 0.9));
    }

    if let Some((month, year)) = extract_month_year(&norm) {
        let start = Date::from_calendar_date(year, month, 1).ok()?;
        let (_, end) = month_bounds(start)?;
        return Some(range(
            text,
            day_start(start, anchor),
            day_end(end, anchor),
            TimeGranularity::Month,
            0.95,
            "month_year",
        ));
    }

    None
}

fn single_day(
    original: &str,
    date: Date,
    anchor: OffsetDateTime,
    rule: &'static str,
    confidence: f32,
) -> NormalizedTime {
    NormalizedTime {
        text: original.to_string(),
        resolved_start: day_start(date, anchor),
        resolved_end: None,
        granularity: TimeGranularity::Day,
        confidence,
        rule,
    }
}

fn range(
    original: &str,
    start: OffsetDateTime,
    end: OffsetDateTime,
    granularity: TimeGranularity,
    confidence: f32,
    rule: &'static str,
) -> NormalizedTime {
    NormalizedTime {
        text: original.to_string(),
        resolved_start: start,
        resolved_end: Some(end),
        granularity,
        confidence,
        rule,
    }
}

fn day_start(date: Date, anchor: OffsetDateTime) -> OffsetDateTime {
    PrimitiveDateTime::new(date, Time::MIDNIGHT).assume_offset(anchor.offset())
}

fn day_end(date: Date, anchor: OffsetDateTime) -> OffsetDateTime {
    let end = Time::from_hms(23, 59, 59).expect("valid time");
    PrimitiveDateTime::new(date, end).assume_offset(anchor.offset())
}

fn week_bounds(date: Date) -> (Date, Date) {
    let offset = date.weekday().number_days_from_monday() as i64;
    let start = date - Duration::days(offset);
    let end = start + Duration::days(6);
    (start, end)
}

fn month_bounds(date: Date) -> Option<(Date, Date)> {
    let start = Date::from_calendar_date(date.year(), date.month(), 1).ok()?;
    let next_month = shift_month(start, 1)?;
    let end = next_month - Duration::days(1);
    Some((start, end))
}

fn shift_month(date: Date, delta: i32) -> Option<Date> {
    let mut year = date.year();
    let mut month_index = date.month() as i32 + delta;

    while month_index < 1 {
        month_index += 12;
        year -= 1;
    }
    while month_index > 12 {
        month_index -= 12;
        year += 1;
    }

    let month = month_from_number(month_index as u8)?;
    Date::from_calendar_date(year, month, 1).ok()
}

fn month_from_number(value: u8) -> Option<Month> {
    match value {
        1 => Some(Month::January),
        2 => Some(Month::February),
        3 => Some(Month::March),
        4 => Some(Month::April),
        5 => Some(Month::May),
        6 => Some(Month::June),
        7 => Some(Month::July),
        8 => Some(Month::August),
        9 => Some(Month::September),
        10 => Some(Month::October),
        11 => Some(Month::November),
        12 => Some(Month::December),
        _ => None,
    }
}

fn previous_weekday(anchor: Date, weekday: Weekday) -> Date {
    let current = anchor.weekday().number_days_from_monday() as i64;
    let target = weekday.number_days_from_monday() as i64;
    let raw = (current - target + 7) % 7;
    let diff = if raw == 0 { 7 } else { raw };
    anchor - Duration::days(diff)
}

fn next_weekday(anchor: Date, weekday: Weekday) -> Date {
    let current = anchor.weekday().number_days_from_monday() as i64;
    let target = weekday.number_days_from_monday() as i64;
    let raw = (target - current + 7) % 7;
    let diff = if raw == 0 { 7 } else { raw };
    anchor + Duration::days(diff)
}

fn shift_by_unit(anchor: Date, value: i64, unit: &str) -> Option<Date> {
    match unit {
        "day" | "days" => Some(anchor + Duration::days(value)),
        "week" | "weeks" => Some(anchor + Duration::weeks(value)),
        "month" | "months" => shift_month(anchor, value as i32),
        _ => None,
    }
}

fn extract_last_next_weekday(norm: &str, prefix: &str) -> Option<Weekday> {
    let parts: Vec<&str> = norm.split_whitespace().collect();
    if parts.len() != 2 || parts[0] != prefix {
        return None;
    }
    parse_weekday(parts[1])
}

fn extract_in_n_unit(norm: &str) -> Option<(u64, &str)> {
    let parts: Vec<&str> = norm.split_whitespace().collect();
    if parts.len() != 3 || parts[0] != "in" {
        return None;
    }
    let n = parts[1].parse::<u64>().ok()?;
    Some((n, parts[2]))
}

fn extract_n_unit_ago(norm: &str) -> Option<(u64, &str)> {
    let parts: Vec<&str> = norm.split_whitespace().collect();
    if parts.len() != 3 || parts[2] != "ago" {
        return None;
    }
    let n = parts[0].parse::<u64>().ok()?;
    Some((n, parts[1]))
}

fn extract_month_year(norm: &str) -> Option<(Month, i32)> {
    let parts: Vec<&str> = norm.split_whitespace().collect();
    if parts.len() != 2 {
        return None;
    }
    let month = parse_month(parts[0])?;
    let year = parts[1].parse::<i32>().ok()?;
    if !(1900..=3000).contains(&year) {
        return None;
    }
    Some((month, year))
}

fn parse_weekday(token: &str) -> Option<Weekday> {
    match token {
        "monday" | "mon" => Some(Weekday::Monday),
        "tuesday" | "tue" | "tues" => Some(Weekday::Tuesday),
        "wednesday" | "wed" => Some(Weekday::Wednesday),
        "thursday" | "thu" | "thurs" => Some(Weekday::Thursday),
        "friday" | "fri" => Some(Weekday::Friday),
        "saturday" | "sat" => Some(Weekday::Saturday),
        "sunday" | "sun" => Some(Weekday::Sunday),
        _ => None,
    }
}

fn parse_month(token: &str) -> Option<Month> {
    match token {
        "january" | "jan" => Some(Month::January),
        "february" | "feb" => Some(Month::February),
        "march" | "mar" => Some(Month::March),
        "april" | "apr" => Some(Month::April),
        "may" => Some(Month::May),
        "june" | "jun" => Some(Month::June),
        "july" | "jul" => Some(Month::July),
        "august" | "aug" => Some(Month::August),
        "september" | "sep" | "sept" => Some(Month::September),
        "october" | "oct" => Some(Month::October),
        "november" | "nov" => Some(Month::November),
        "december" | "dec" => Some(Month::December),
        _ => None,
    }
}

fn normalized_text(input: &str) -> String {
    input
        .trim()
        .to_ascii_lowercase()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == ' ' {
                c
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use time::UtcOffset;

    fn anchor() -> OffsetDateTime {
        PrimitiveDateTime::new(
            Date::from_calendar_date(2023, Month::May, 8).expect("valid date"),
            Time::from_hms(13, 56, 0).expect("valid time"),
        )
        .assume_offset(UtcOffset::UTC)
    }

    #[test]
    fn normalizes_yesterday() {
        let out = normalize_relative_time("yesterday", anchor()).expect("should parse");
        assert_eq!(out.rule, "yesterday");
        assert_eq!(
            out.resolved_start.date(),
            Date::from_calendar_date(2023, Month::May, 7).expect("valid date")
        );
    }

    #[test]
    fn normalizes_last_friday() {
        let out = normalize_relative_time("last Friday", anchor()).expect("should parse");
        assert_eq!(out.rule, "last_weekday");
        assert_eq!(
            out.resolved_start.date(),
            Date::from_calendar_date(2023, Month::May, 5).expect("valid date")
        );
    }

    #[test]
    fn normalizes_in_n_days() {
        let out = normalize_relative_time("in 3 days", anchor()).expect("should parse");
        assert_eq!(out.rule, "in_n_unit");
        assert_eq!(
            out.resolved_start.date(),
            Date::from_calendar_date(2023, Month::May, 11).expect("valid date")
        );
    }

    #[test]
    fn normalizes_n_weeks_ago() {
        let out = normalize_relative_time("2 weeks ago", anchor()).expect("should parse");
        assert_eq!(out.rule, "n_unit_ago");
        assert_eq!(
            out.resolved_start.date(),
            Date::from_calendar_date(2023, Month::April, 24).expect("valid date")
        );
    }

    #[test]
    fn normalizes_month_year_to_range() {
        let out = normalize_relative_time("June 2023", anchor()).expect("should parse");
        assert_eq!(out.rule, "month_year");
        assert_eq!(out.granularity, TimeGranularity::Month);
        assert_eq!(
            out.resolved_start.date(),
            Date::from_calendar_date(2023, Month::June, 1).expect("valid date")
        );
        assert_eq!(
            out.resolved_end.expect("range should have end").date(),
            Date::from_calendar_date(2023, Month::June, 30).expect("valid date")
        );
    }

    #[test]
    fn unknown_phrase_returns_none() {
        let out = normalize_relative_time("sometime soon", anchor());
        assert!(out.is_none());
    }
}
