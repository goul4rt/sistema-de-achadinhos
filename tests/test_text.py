from achadinhos.text import contains_term, fingerprint, normalize


def _hay(text):
    t = normalize(text)
    return set(t.split()), t


def test_normalize_removes_accents_and_symbols():
    assert normalize("Tênis   Mizuno – Feminino!") == "tenis mizuno feminino"


def test_contains_term_all_words_any_order():
    toks, text = _hay("Fritadeira Air Fryer Mondial 4L")
    assert contains_term(toks, text, "fryer air")
    assert contains_term(toks, text, "mondial")
    assert not contains_term(toks, text, "air fryer philips")


def test_contains_term_prefix_and_phrase():
    toks, text = _hay("Fones de ouvido Bluetooth")
    assert contains_term(toks, text, "fone")  # prefixo
    assert contains_term(toks, text, '"fones de ouvido"')
    assert not contains_term(toks, text, '"ouvido fones"')


def test_fingerprint_ignores_order_case_and_stopwords():
    a = fingerprint("Smart TV Samsung 50 polegadas", "Amazon")
    b = fingerprint("samsung smart tv de 50 Polegadas", "amazon")
    assert a == b
    assert a != fingerprint("Smart TV Samsung 50 polegadas", "Magalu")
