from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[1] / "src/memebot/ui.py"


def test_empty_workbench_has_setup_and_navigation(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert any("Daily desk" in title.value for title in app.title)
    assert any("Collect" in button.label for button in app.button)
    app.sidebar.radio[0].set_value("Settings").run()
    assert not app.exception
    assert any("YouTube API key" in field.label for field in app.text_input)


def test_sources_empty_state_and_invalid_channel_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    app.sidebar.radio[0].set_value("Sources").run()
    assert not app.exception
    app.text_input(key="source_id").set_value("bad")
    app.text_input(key="source_name").set_value("Test")
    app.button(key="add_source").click().run()
    assert not app.exception
    assert any("channel ID" in e.value for e in app.error)
