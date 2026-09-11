from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "templates" / "dashboard.html"


def wrap_secondary_hidden_links(text, targets):
    """Hide Primary-only dashboard actions from Secondary roles, even on minified lines."""
    for target in targets:
        pattern = re.compile(
            r'<a href="\{\{ url_for\(\'' + re.escape(target) + r'\'\) \}\}"(?P<body>.*?)</a>',
            re.DOTALL,
        )
        pos = 0
        chunks = []
        while True:
            match = pattern.search(text, pos)
            if not match:
                chunks.append(text[pos:])
                break
            chunks.append(text[pos:match.start()])
            prefix = text[max(0, match.start() - 80):match.start()]
            link = match.group(0)
            if prefix.rstrip().endswith('{% if not is_secondary %}'):
                chunks.append(link)
            else:
                chunks.append('{% if not is_secondary %}' + link + '{% endif %}')
            pos = match.end()
        text = ''.join(chunks)
    return text


def main():
    text = DASHBOARD.read_text(encoding="utf-8")
    text = wrap_secondary_hidden_links(
        text,
        ["add_membership", "memberships_list", "farmers_list", "farms_list", "crops_list", "harvests_list"],
    )
    DASHBOARD.write_text(text, encoding="utf-8")
    print("Secondary dashboard Primary-only links hidden.")


if __name__ == "__main__":
    main()
