from datetime import date

from complaint_radar.summarize.explain import explain, facts_text, template_summary

ALERT = {
    "company": "MOHELA",
    "product": "Student loan",
    "issue": "Dealing with your lender or servicer",
    "week_start": date(2022, 10, 10),
    "n": 120,
    "expected": 15.0,
    "score": 8.0,
    "pattern": "single_company",
    "wave_companies": 1,
}
EXAMPLES = ["My account says TEACH Grant only and I cannot make a payment.", "My loans were transferred and lost."]


class Fake:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.prompts = reply, error, []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.reply


def test_template_summary_states_the_facts():
    s = template_summary(ALERT)
    assert "MOHELA" in s and "120" in s and "15" in s and "8.0x" in s and "2022-10-10" in s


def test_llm_summary_used_when_grounded():
    reply = "MOHELA got 120 complaints about servicing, 8 times the usual 15. Borrowers report blocked payments."
    out = explain(ALERT, EXAMPLES, client=Fake(reply))
    assert out["method"] == "llm" and out["summary"] == reply


def test_prompt_contains_facts_examples_and_rules():
    fake = Fake("MOHELA got 120 complaints.")
    explain(ALERT, EXAMPLES, client=fake)
    p = fake.prompts[0]
    assert "TEACH Grant" in p and "120" in p and "Do not invent" in p


def test_falls_back_when_model_invents_numbers():
    out = explain(ALERT, EXAMPLES, client=Fake("MOHELA got 950 complaints, up 400 percent."))
    assert out["method"] == "template" and "unsupported numbers" in out["fallback_reason"]


def test_falls_back_when_model_unavailable():
    out = explain(ALERT, EXAMPLES, client=Fake(error=ConnectionError("no server")))
    assert out["method"] == "template" and "ConnectionError" in out["fallback_reason"]


def test_no_client_means_template():
    assert explain(ALERT, EXAMPLES, client=None)["method"] == "template"


def test_wave_is_mentioned_in_template():
    wave = ALERT | {"pattern": "cross_company_wave", "wave_companies": 15}
    assert "15 companies" in template_summary(wave)


def test_facts_text_lists_numbers():
    f = facts_text(ALERT)
    assert "120" in f and "15" in f


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, tags=None, reply="ok"):
        self.tags, self.reply, self.posts = tags or {"models": []}, reply, []

    def get(self, url, timeout):
        return Resp(self.tags)

    def post(self, url, json, timeout):
        self.posts.append(json)
        return Resp({"response": self.reply})


def test_ollama_client_request_shape_and_availability():
    from complaint_radar.summarize.ollama import OllamaClient

    s = Session(tags={"models": [{"name": "qwen2.5:1.5b"}]}, reply="hello")
    c = OllamaClient(session=s)
    assert c.available() and c.generate("hi") == "hello"
    assert s.posts[0]["stream"] is False and s.posts[0]["options"]["temperature"] == 0.2
    assert not OllamaClient(session=Session()).available()


def test_llm_summary_capped_at_three_sentences():
    reply = "MOHELA got 120 complaints. That is 8 times the usual 15. People cannot pay. Some are angry. More detail."
    out = explain(ALERT, EXAMPLES, client=Fake(reply))
    assert out["summary"] == "MOHELA got 120 complaints. That is 8 times the usual 15. People cannot pay."
