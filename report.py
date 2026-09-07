"""
Builds an HTML email from the ranked results and sends it via SMTP.

Reads credentials from environment variables (set as GitHub Secrets):
    SMTP_HOST     e.g. smtp.gmail.com
    SMTP_PORT     e.g. 587
    SMTP_USER     the sending address
    SMTP_PASS     an app password, NOT your normal password
    MAIL_TO       where to send it (defaults to SMTP_USER)

If SMTP_USER or SMTP_PASS is missing, sending is skipped and the HTML is
just written to disk. That makes local testing safe.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

CSS = """
body{font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#1a1a1a;line-height:1.5}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:13px}
th{background:#1F3864;color:#fff;text-align:left;padding:8px 10px;font-weight:600}
td{padding:7px 10px;border-bottom:1px solid #e5e5e5}
tr:nth-child(even) td{background:#fafafa}
.num{text-align:right;font-variant-numeric:tabular-nums}
.tk{font-weight:600}
.note{font-size:12px;color:#666;margin-top:20px;border-top:1px solid #e5e5e5;padding-top:12px}
h2{font-size:17px;margin:0 0 4px}
.sub{font-size:13px;color:#666;margin:0 0 16px}
.none{background:#f5f5f5;padding:16px;border-radius:6px;color:#555}
"""

COLUMNS = [
    ("ticker", "Ticker", "tk"),
    ("score", "Score", "num"),
    ("price", "Price", "num"),
    ("rsi14", "RSI", "num"),
    ("pullback_pct_below_sma50", "% below 50d", "num"),
    ("coil_ratio", "Coil", "num"),
    ("rel_strength_pct_vs_spy", "RS vs SPY", "num"),
    ("suggested_stop", "Stop", "num"),
    ("suggested_target", "Target", "num"),
]


def build_html(df, run_date, scanned, bench_return, top_n=10):
    if df is None or len(df) == 0:
        body = (
            '<div class="none">No candidates passed the filters today. '
            "That is a normal result, not a failure. In a broad downtrend "
            "this screen should return nothing.</div>"
        )
    else:
        head = "".join(f"<th>{label}</th>" for _, label, _ in COLUMNS)
        rows = []
        for _, r in df.head(top_n).iterrows():
            cells = []
            for key, _, cls in COLUMNS:
                v = r[key]
                if key == "price" or key in ("suggested_stop", "suggested_target"):
                    txt = f"${v:,.2f}"
                elif key in ("pullback_pct_below_sma50", "rel_strength_pct_vs_spy"):
                    txt = f"{v:+.2f}%"
                elif key == "rsi14":
                    txt = f"{v:.0f}"
                else:
                    txt = f"{v:.3f}" if isinstance(v, float) else str(v)
                cells.append(f'<td class="{cls}">{txt}</td>')
            rows.append("<tr>" + "".join(cells) + "</tr>")
        body = f"<table><tr>{head}</tr>{''.join(rows)}</table>"

    n = 0 if df is None else len(df)
    return f"""<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h2>Swing scan &mdash; {run_date}</h2>
<p class="sub">{n} of {scanned} tickers passed the filters.
SPY 60-day return: {bench_return:+.1%}</p>
{body}
<div class="note">
<b>Before you act on any of this:</b> these are screen results, not
recommendations. The scoring weights and the stop/target multiples are
untested starting assumptions, not findings. Log every name here in your
trade log &mdash; including the ones you skip &mdash; and judge the screen on
30+ closed trades, not on any single day.<br><br>
Stops and targets are 1.5x and 3x ATR(14), a convention rather than a
result. Not investment advice.
</div>
</body></html>"""


def send(html, subject, out_path="report.html"):
    """Write the HTML to disk, and email it if credentials are present."""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO") or user

    if not user or not password:
        print(f"No SMTP credentials set - skipped sending. Wrote {out_path}")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(
        "This report is formatted as HTML. "
        "Open it in a mail client that renders HTML."
    )
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)

    print(f"Emailed report to {to}")
    return True
