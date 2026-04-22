import os, requests
from datetime import datetime, timezone
from collections import defaultdict

JIRA_DOMAIN   = os.environ["JIRA_DOMAIN"]
JIRA_EMAIL    = os.environ["JIRA_EMAIL"]
JIRA_TOKEN    = os.environ["JIRA_TOKEN"]
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", )

PROJECTS = ["AT", "CT", "IT", "MED", "SMM", "DS", "CRM", "NTFRD"]
STATUS_EMOJI = {"done":"✅","in progress":"🔄","blocked":"🚫","to do":"📋","in review":"👀"}

def jira_post(path, payload):
    url = f"https://{JIRA_DOMAIN}/rest/api/3{path}"
    resp = requests.post(url, auth=(JIRA_EMAIL, JIRA_TOKEN),
                         headers={"Content-Type": "application/json"},
                         json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()

def jira_get(path, params=None):
    url = f"https://{JIRA_DOMAIN}/rest/api/3{path}"
    resp = requests.get(url, auth=(JIRA_EMAIL, JIRA_TOKEN), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

def get_last_comment(issue_key):
    try:
        data = jira_get(f"/issue/{issue_key}/comment", params={"maxResults": 1, "orderBy": "-created"})
        comments = data.get("comments", [])
        if not comments:
            return ""
        body = comments[-1].get("body", {})
        if isinstance(body, str):
            return body[:200]
        for block in body.get("content", []):
            for inline in block.get("content", []):
                text = inline.get("text", "").strip()
                if text:
                    return text[:200]
        return ""
    except Exception:
        return ""

def fetch_issues():
    project_list = ", ".join(PROJECTS)
    today = datetime.now().strftime("%Y-%m-%d")
    jql = f'project in ({project_list}) AND updated >= "{today}" ORDER BY assignee ASC, status ASC'
    all_issues = []
    next_token = None

    while True:
        payload = {
            "jql": jql,
            "maxResults": 50,
            "fields": ["summary", "status", "assignee", "project"]
        }
        if next_token:
            payload["nextPageToken"] = next_token

        data = jira_post("/search/jql", payload)
        issues = data.get("issues", [])
        all_issues.extend(issues)
        print(f"   Загружено: {len(all_issues)}")

        if data.get("isLast", True):
            break
        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return all_issues

def status_emoji(name):
    key = name.lower()
    for k, e in STATUS_EMOJI.items():
        if k in key: return e
    return "⬜"

def build_slack_message(issues):
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for issue in issues:
        f = issue["fields"]
        a = (f.get("assignee") or {}).get("displayName", "Unassigned")
        p = f.get("project", {}).get("key", "?")
        s = f.get("status", {}).get("name", "Unknown")
        grouped[a][p][s].append((issue["key"], f.get("summary", "")))

    blocks = [
        {"type":"header","text":{"type":"plain_text","text":f"📊 Daily Report — {today}","emoji":True}},
        {"type":"divider"}
    ]

    for assignee, projects in sorted(grouped.items()):
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":f"*👤 {assignee}*"}})
        for proj, statuses in sorted(projects.items()):
            lines = [f"_Проект: {proj}_"]
            for status, tasks in sorted(statuses.items()):
                lines.append(f"\n*{status_emoji(status)} {status}*")
                for key, summary in tasks:
                    comment = get_last_comment(key)
                    url = f"https://{JIRA_DOMAIN}/browse/{key}"
                    line = f"• <{url}|{key}> — {summary}"
                    if comment: line += f"\n  _{comment}_"
                    lines.append(line)
            blocks.append({"type":"section","text":{"type":"mrkdwn","text":"\n".join(lines)}})
        blocks.append({"type":"divider"})

    if len(blocks) == 2:
        blocks.append({"type":"section","text":{"type":"mrkdwn","text":"🕳 Сегодня обновлённых задач не найдено."}})
    return blocks

def send_to_slack(blocks):
    resp = requests.post(SLACK_WEBHOOK, json={"blocks": blocks}, timeout=10)
    print("✅ Отправлено в Slack!" if resp.status_code == 200 else f"❌ Slack: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    print("🔍 Забираем задачи из Jira...")
    issues = fetch_issues()
    print(f"   Итого: {len(issues)} задач")
    print("📝 Формируем отчёт...")
    blocks = build_slack_message(issues)
    print("📤 Отправляем в Slack...")
    send_to_slack(blocks)
