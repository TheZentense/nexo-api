from scripts import local_key


def test_local_key_is_kept_and_not_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(local_key, "__file__", str(tmp_path / "scripts" / "local_key.py"))
    local_key.main()
    target = tmp_path / ".local" / "jwt.key"
    first = target.read_text(encoding="utf-8")
    assert len(first) >= 43
    local_key.main()
    assert target.read_text(encoding="utf-8") == first
    assert first not in capsys.readouterr().out
