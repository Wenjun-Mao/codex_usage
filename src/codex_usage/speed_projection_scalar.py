"""JSON scalar grammar states, without retaining ignored numeric payloads."""


def begin_scalar(char):
    literal = {"t": "true", "f": "false", "n": "null"}.get(char)
    if literal:
        return {"literal": literal, "position": 1}
    return {"number": "sign" if char == "-" else "zero" if char == "0" else "integer"}


def advance_scalar(state, char):
    if "literal" in state:
        position = state["position"]
        literal = state["literal"]
        if position >= len(literal) or char != literal[position]:
            return False
        state["position"] += 1
        return True
    form = state["number"]
    digit = char in "0123456789"
    if form == "sign" and digit:
        new = "zero" if char == "0" else "integer"
    elif form == "integer" and digit:
        new = "integer"
    elif form in {"integer", "zero"} and char == ".":
        new = "dot"
    elif form in {"dot", "fraction"} and digit:
        new = "fraction"
    elif form in {"integer", "zero", "fraction"} and char in "eE":
        new = "exponent"
    elif form == "exponent" and char in "+-":
        new = "exponent_sign"
    elif form in {"exponent", "exponent_sign", "exponent_digits"} and digit:
        new = "exponent_digits"
    else:
        return False
    state["number"] = new
    return True


def scalar_complete(state):
    if "literal" in state:
        return state["position"] == len(state["literal"])
    return state["number"] in {"zero", "integer", "fraction", "exponent_digits"}
