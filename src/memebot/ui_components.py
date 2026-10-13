"""Shared appearance and interaction primitives for all workbench pages."""

import json
from importlib.resources import files

import streamlit as st

from .store import Store
from .worker import queue_job


def theme():
    data = json.loads(files("memebot").joinpath("data/theme.json").read_text())
    c = data["colors"]
    t = data["typography"]
    st.html(f"""<style>
    :root {{ --mb-ink:{c["ink"]}; --mb-muted:{c["muted"]}; --mb-border:{c["border"]}; --mb-primary:{c["primary"]}; }}
    .stApp {{ background:{c["background"]}; color:var(--mb-ink); font-family:{t["body"]["fontFamily"]}; }}
    .stMainBlockContainer {{ max-width:1280px; padding-top:2.2rem; }}
    h1,h2,h3 {{font-family:{t["display"]["fontFamily"]} !important;letter-spacing:-.035em;}}
    h1 {{font-size:2.8rem !important;}} h3 {{font-size:1.2rem !important;}}
    [data-testid="stSidebar"] {{background:{c["surface"]};border-right:1px solid var(--mb-border);}}
    .mb-eyebrow {{font-family:{t["utility"]["fontFamily"]};color:var(--mb-muted);font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.4rem;}}
    .mb-line {{height:4px;background:var(--mb-primary);width:42px;margin-bottom:1.2rem;border-radius:2px;}}
    [data-testid="stVerticalBlockBorderWrapper"] {{background:{c["surface"]};border-radius:12px;}}
    button,a,[role="button"] {{cursor:pointer;}} button:disabled {{cursor:not-allowed;}}
    :focus-visible {{outline:3px solid var(--mb-primary) !important;outline-offset:3px;}}
    textarea {{resize:none !important;}}
    * {{scrollbar-width:thin;scrollbar-color:{c["muted"]} {c["background"]};}}
    *::-webkit-scrollbar {{width:10px;height:10px;}}
    *::-webkit-scrollbar-thumb {{background:{c["muted"]};border-radius:8px;}}
    *::-webkit-scrollbar-track {{background:{c["background"]};}}
    *::-webkit-scrollbar-thumb:hover {{background:{c["primary"]};}}
    @media (max-width:1100px) {{
      [data-testid="stHorizontalBlock"] {{flex-direction:column;}}
      [data-testid="stColumn"] {{width:100% !important;flex:1 1 100% !important;}}
    }}
    @media (max-width:760px) {{ h1 {{font-size:2rem !important;}} }}
    @media (prefers-reduced-motion:reduce) {{* {{animation:none !important;transition:none !important;}}}}
    @media (forced-colors:active) {{* {{scrollbar-color:auto;}}}}
    </style>""")


def header(title, subtitle):
    st.html('<div class="mb-eyebrow">MEMEBOT / EDIT SUITE</div><div class="mb-line"></div>')
    st.title(title)
    st.caption(subtitle)
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)


def action(callback, success="Saved"):
    try:
        callback()
        st.session_state["flash"] = success
        st.rerun()
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))


def queue(config, kind, payload):
    action(
        lambda: queue_job(config, kind, payload),
        "Job queued. You can keep reviewing while it runs.",
    )


def duration(seconds):
    seconds = max(0, round(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02}"


@st.fragment(run_every=3)
def jobs_panel(config):
    rows = Store(config.db_path).all("SELECT * FROM jobs ORDER BY id DESC LIMIT 8")
    active = [r for r in rows if r["status"] in ("queued", "running")]
    if active:
        st.caption("BACKGROUND WORK")
        for r in active:
            st.progress(r["progress"], text=f"{r['kind'].capitalize()} · {r['status']}")
            if r["message"]:
                st.caption(r["message"][:160])
    completed = tuple((r["id"], r["status"]) for r in rows if r["status"] in ("done", "failed"))
    previous = st.session_state.get("completed_jobs")
    st.session_state["completed_jobs"] = completed
    if previous is not None and completed != previous:
        st.rerun()
