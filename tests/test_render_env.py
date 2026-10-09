"""deploy/render_env.py builds the server's .env; a wrong quote there breaks a deploy."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "render_env.py"
spec = importlib.util.spec_from_file_location("render_env", SCRIPT)
render_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_env)

PATH = "/survey/prod"


def param(name, value):
    return {"Name": f"{PATH}/{name}", "Value": value}


def test_strips_prefix_sorts_and_single_quotes_values():
    out = render_env.render([param("SECRET_KEY", "abc"), param("ALLOWED_HOSTS", "a.example")], PATH)
    assert out == "ALLOWED_HOSTS='a.example'\nSECRET_KEY='abc'\n"


def test_trailing_slash_on_path_is_fine():
    assert render_env.render([param("X", "1")], PATH + "/") == "X='1'\n"


def test_values_with_spaces_dollars_and_hashes_are_kept_literally():
    out = render_env.render([param("FROM", "Accelerare <n@x.org> $HOME # not a comment")], PATH)
    assert out == "FROM='Accelerare <n@x.org> $HOME # not a comment'\n"


@pytest.mark.parametrize("bad", ["it's", "two\nlines", "carriage\rreturn"])
def test_unquotable_values_are_refused_without_echoing_the_value(bad):
    with pytest.raises(ValueError) as error:
        render_env.render([param("SECRET_KEY", bad)], PATH)
    assert "SECRET_KEY" in str(error.value)
    assert bad not in str(error.value)


def test_parameter_outside_the_path_is_refused():
    with pytest.raises(ValueError):
        render_env.render([{"Name": "/other/X", "Value": "1"}], PATH)


def test_nested_or_invalid_names_are_refused():
    with pytest.raises(ValueError):
        render_env.render([param("sub/X", "1")], PATH)
    with pytest.raises(ValueError):
        render_env.render([param("BAD-NAME", "1")], PATH)


def test_empty_result_is_refused():
    with pytest.raises(ValueError):
        render_env.render([], PATH)
