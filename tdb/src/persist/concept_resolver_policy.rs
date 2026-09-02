pub fn is_stopword_zh(s: &str) -> bool {
    matches!(
        s,
        "你" | "我"
            | "他"
            | "她"
            | "它"
            | "我们"
            | "你们"
            | "他们"
            | "她们"
            | "这"
            | "那"
            | "此"
            | "其"
            | "之"
            | "者"
            | "也"
            | "了"
            | "的"
            | "啊"
            | "呀"
            | "呢"
            | "么"
            | "吗"
            | "一个"
            | "一些"
            | "这个"
            | "那个"
            | "这里"
            | "那里"
    )
}

pub fn is_allowlist_entity_exact(s: &str) -> bool {
    matches!(s, "大神" | "大王" | "大仙" | "行者" | "师父" | "菩萨")
}

pub fn contains_han(s: &str) -> bool {
    s.chars()
        .any(|c| ('\u{4E00}'..='\u{9FFF}').contains(&c) || ('\u{3400}'..='\u{4DBF}').contains(&c))
}

pub fn char_len(s: &str) -> usize {
    s.chars().count()
}

pub fn normalize_surface(s: &str) -> String {
    s.trim_matches(|c: char| {
        matches!(
            c,
            '“' | '”'
                | '‘'
                | '’'
                | '《'
                | '》'
                | '「'
                | '」'
                | '『'
                | '』'
                | '（'
                | '）'
                | '('
                | ')'
                | '【'
                | '】'
                | '，'
                | '。'
                | '！'
                | '？'
                | '；'
                | '：'
                | '、'
                | ','
                | '.'
                | '!'
                | '?'
                | ';'
                | ':'
                | '"'
                | '\''
                | ' '
                | '\t'
                | '\n'
                | '\r'
        )
    })
    .trim()
    .to_string()
}

pub fn allow_single_char_topic(s: &str) -> bool {
    matches!(s, "佛" | "仙" | "妖" | "魔" | "神" | "人")
}

pub fn normalize_entity_surface(surface: &str) -> String {
    let s = normalize_surface(surface);
    if s.is_empty() {
        return s;
    }

    let prefixes_multi = [
        "我们", "你们", "他们", "她们", "这些", "那些", "这个", "那个", "其中",
    ];
    let prefixes_single = ["你", "我", "他", "她", "它", "这", "那", "此", "其"];
    let prefixes_conj = ["与", "和", "同", "跟", "及", "并", "且"];

    let mut out = s;
    let mut stripped = false;
    for p in prefixes_multi {
        if out.starts_with(p) {
            let rest = out[p.len()..].to_string();
            if contains_han(&rest) && char_len(&rest) >= 2 {
                out = rest;
                stripped = true;
            }
            break;
        }
    }
    if !stripped {
        for p in prefixes_single {
            if out.starts_with(p) {
                let rest = out[p.len()..].to_string();
                if contains_han(&rest) && char_len(&rest) >= 2 {
                    out = rest;
                    stripped = true;
                }
                break;
            }
        }
    }
    if !stripped {
        for p in prefixes_conj {
            if out.starts_with(p) {
                let rest = out[p.len()..].to_string();
                if contains_han(&rest) && char_len(&rest) >= 2 {
                    out = rest;
                }
                break;
            }
        }
    }
    normalize_surface(&out)
}

pub fn is_low_info_phrase_zh(surface: &str) -> bool {
    matches!(
        surface,
        "出去"
            | "进来"
            | "回来"
            | "过去"
            | "起来"
            | "下去"
            | "上来"
            | "进去"
            | "出来"
            | "想必"
            | "好歹"
            | "原来"
            | "果然"
            | "只好"
            | "如何"
            | "莫非"
    )
}

pub fn is_verbish_short_phrase_zh(surface: &str) -> bool {
    if char_len(surface) > 4 {
        return false;
    }
    ["去", "来", "上", "下", "出", "进", "回", "过", "起"]
        .iter()
        .any(|s| surface.ends_with(s))
}

pub fn entity_rejection_reason(surface: &str) -> Option<&'static str> {
    let s = normalize_entity_surface(surface);
    if s.is_empty() || is_stopword_zh(&s) {
        return Some("stopword");
    }
    if !contains_han(&s) {
        return Some("no_han");
    }
    if char_len(&s) < 2 {
        return Some("too_short");
    }
    if is_low_info_phrase_zh(&s) {
        return Some("low_info_phrase");
    }
    if !is_allowlist_entity_exact(&s) && is_verbish_short_phrase_zh(&s) {
        return Some("verbish_suffix");
    }
    None
}

pub fn should_create_entity(surface: &str) -> bool {
    entity_rejection_reason(surface).is_none()
}

pub fn should_create_topic(surface: &str) -> bool {
    let s = normalize_surface(surface);
    if s.is_empty() || is_stopword_zh(&s) || !contains_han(&s) {
        return false;
    }
    char_len(&s) >= 2 || allow_single_char_topic(&s)
}

pub fn should_create_location(surface: &str) -> bool {
    let s = normalize_surface(surface);
    if s.is_empty() || is_stopword_zh(&s) {
        return false;
    }
    contains_han(&s) && char_len(&s) >= 2
}
