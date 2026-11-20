use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Serialize, PartialEq)]
pub struct Glance {
    pub attention_count: usize,
    pub rows: Vec<GlanceRow>,
}

#[derive(Debug, Serialize, PartialEq)]
pub struct GlanceRow {
    pub session_id: String,
    pub depth: u8,
    pub children: Vec<String>,
    pub parent_session_id: Option<String>,
    pub mark: String,
    pub agent_type: String,
    pub name: String,
    pub title: String,
    pub status: String,
    pub project: String,
    pub summary: String,
    pub directory: String,
    pub token_total: Option<i64>,
    pub cpu_percent: Option<f64>,
    pub memory_bytes: Option<i64>,
    pub age_seconds: Option<i64>,
}

#[derive(Deserialize)]
struct Live {
    active: Vec<Value>,
    attention: Vec<Value>,
    #[serde(default)]
    corrupt: bool,
}

pub fn glance_from_live(body: &str) -> Result<Glance, String> {
    let live: Live = serde_json::from_str(body).map_err(|e| e.to_string())?;
    if live.corrupt {
        return Err("registry is corrupt".into());
    }
    let mut flat = Vec::new();
    for value in live.attention.iter().chain(live.active.iter()) {
        flat.push(row_from(value)?);
    }
    let ids: Vec<String> = flat.iter().map(|r| r.session_id.clone()).collect();
    for row in &mut flat {
        if row
            .parent_session_id
            .as_ref()
            .is_some_and(|id| ids.contains(id))
        {
            row.depth = 1;
        }
    }
    // Owned parent links so filling `children` does not borrow `flat` twice.
    let links: Vec<(String, Option<String>)> = flat
        .iter()
        .map(|row| (row.session_id.clone(), row.parent_session_id.clone()))
        .collect();
    for row in &mut flat {
        row.children = links
            .iter()
            .filter(|(_, parent)| parent.as_deref() == Some(row.session_id.as_str()))
            .map(|(id, _)| id.clone())
            .collect();
    }
    let attention_count = live.attention.len();
    Ok(Glance {
        attention_count,
        rows: flat,
    })
}

fn row_from(value: &Value) -> Result<GlanceRow, String> {
    let session_id = text(value, "session_id");
    if session_id.is_empty() {
        return Err("session missing session_id".into());
    }
    let agent_type = text(value, "agent_type");
    Ok(GlanceRow {
        session_id,
        depth: 0,
        children: Vec::new(),
        parent_session_id: value
            .get("parent_session_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .filter(|s| !s.is_empty()),
        mark: mark(&agent_type),
        name: first_nonempty(&[
            text(value, "peer_name"),
            text(value, "title"),
            text(value, "session_id"),
        ]),
        title: text(value, "title"),
        status: text(value, "status"),
        project: text(value, "project"),
        summary: text(value, "summary"),
        directory: text(value, "directory"),
        token_total: token_total(&agent_type, value.get("tokens")),
        cpu_percent: value.get("cpu_percent").and_then(|v| v.as_f64()),
        memory_bytes: value.get("memory_bytes").and_then(|v| v.as_i64()),
        age_seconds: age_seconds(value.get("last_ping")),
        agent_type,
    })
}

fn mark(agent_type: &str) -> String {
    match agent_type {
        "claude" => "C".to_string(),
        "codex" => "X".to_string(),
        "cursor" => ">".to_string(),
        other => other.chars().next().unwrap_or('?').to_string(),
    }
}

fn token_total(agent_type: &str, tokens: Option<&Value>) -> Option<i64> {
    let tokens = tokens?.as_object()?;
    match agent_type {
        "claude" => Some(int(tokens.get("input_tokens")) + int(tokens.get("output_tokens"))),
        "codex" => Some(int(tokens.get("total_tokens"))),
        _ => None,
    }
}

fn int(value: Option<&Value>) -> i64 {
    value.and_then(|v| v.as_i64()).unwrap_or(0)
}

fn text(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}

fn first_nonempty(parts: &[String]) -> String {
    parts
        .iter()
        .find(|s| !s.is_empty())
        .cloned()
        .unwrap_or_default()
}

fn age_seconds(value: Option<&Value>) -> Option<i64> {
    let text = value?.as_str()?;
    let parsed = chrono::DateTime::parse_from_rfc3339(text).ok()?;
    let seconds = (chrono::Utc::now() - parsed.with_timezone(&chrono::Utc)).num_seconds();
    Some(seconds.max(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attention_precedes_active_and_stale_is_hidden() {
        let raw = r#"{
          "attention": [{"session_id": "b", "agent_type": "claude", "status": "blocked", "parent_session_id": null}],
          "active": [{"session_id": "a", "agent_type": "cursor", "status": "working", "parent_session_id": null}],
          "stale": [{"session_id": "b", "agent_type": "claude", "status": "blocked", "parent_session_id": null}]
        }"#;
        let glance = glance_from_live(raw).unwrap();
        let ids: Vec<_> = glance.rows.iter().map(|r| r.session_id.as_str()).collect();
        assert_eq!(ids, ["b", "a"]);
        assert_eq!(glance.attention_count, 1);
    }

    #[test]
    fn child_nests_under_parent_and_orphan_keeps_parent_id() {
        let raw = r#"{
          "attention": [],
          "active": [
            {"session_id": "parent", "agent_type": "claude", "status": "working", "parent_session_id": null},
            {"session_id": "child", "agent_type": "codex", "status": "working", "parent_session_id": "parent"},
            {"session_id": "orphan", "agent_type": "cursor", "status": "working", "parent_session_id": "gone"}
          ],
          "stale": []
        }"#;
        let glance = glance_from_live(raw).unwrap();
        let parent = glance.rows.iter().find(|r| r.session_id == "parent").unwrap();
        assert_eq!(parent.children, ["child"]);
        let orphan = glance.rows.iter().find(|r| r.session_id == "orphan").unwrap();
        assert_eq!(orphan.parent_session_id.as_deref(), Some("gone"));
        assert!(glance.rows.iter().all(|r| r.session_id != "child" || r.depth == 1));
    }

    #[test]
    fn token_total_and_no_registry_id() {
        let raw = r#"{
          "attention": [],
          "active": [
            {"session_id": "c", "agent_type": "claude", "status": "working", "registry_id": "secret",
             "tokens": {"input_tokens": 3, "output_tokens": 4}},
            {"session_id": "x", "agent_type": "codex", "status": "working",
             "tokens": {"total_tokens": 9}},
            {"session_id": "u", "agent_type": "cursor", "status": "working"}
          ],
          "stale": []
        }"#;
        let glance = glance_from_live(raw).unwrap();
        let claude = glance.rows.iter().find(|r| r.session_id == "c").unwrap();
        assert_eq!(claude.token_total, Some(7));
        assert_eq!(claude.mark, "C");
        let codex = glance.rows.iter().find(|r| r.session_id == "x").unwrap();
        assert_eq!(codex.token_total, Some(9));
        assert_eq!(codex.mark, "X");
        let cursor = glance.rows.iter().find(|r| r.session_id == "u").unwrap();
        assert_eq!(cursor.token_total, None);
        assert_eq!(cursor.mark, ">");
        let text = serde_json::to_string(&glance).unwrap();
        assert!(!text.contains("secret"));
        assert!(!text.contains("registry_id"));
    }

    #[test]
    fn corrupt_live_is_an_error() {
        let raw = r#"{"active": [], "stale": [], "attention": [], "corrupt": true}"#;
        let err = glance_from_live(raw).unwrap_err();
        assert_eq!(err, "registry is corrupt");
    }
}
