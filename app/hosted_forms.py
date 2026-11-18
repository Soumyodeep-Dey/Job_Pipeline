"""Fill a supported public application form with confirmed facts only."""
import re
from urllib.parse import urlsplit
from hashlib import sha256

from app.form_questions import ReviewNeeded, QuestionsNeeded, fingerprint

FIELDS = {
    "first name":"given_name", "last name":"family_name", "name":"full_name", "full name":"full_name", "email":"email", "email address":"email",
    "current location":"current_city", "phone":"phone", "phone number":"phone",
    "linkedin":"linkedin_url", "linkedin profile":"linkedin_url", "linkedin url":"linkedin_url",
    "portfolio":"portfolio_url", "portfolio url":"portfolio_url",
}
SPONSORSHIP = "would you require visa sponsorship to work in the country in which this position is based?"
RECEIPT = re.compile(r"^(?:Your application was successfully submitted\.(?: We'll contact you if there are next steps\.)?|Application submitted!?|Your application has been submitted\.?|Thank you for applying\.)$",re.I)

def normalized(text):
    return " ".join(text.replace("*","").casefold().split())

def guard_routes(context, host):
    # Isolate the browser from localhost, the database and unrelated destinations.
    families = ("ashbyhq.com","ashbyprd.s3.amazonaws.com") if host.endswith("ashbyhq.com") else (
        ("lever.co",) if host.endswith("lever.co") else ("greenhouse.io", "greenhouse.com"))
    def route_request(route):
        url = urlsplit(route.request.url)
        name = url.hostname or ""
        allowed = url.scheme == "https" and url.netloc == name and any(
            name == domain or name.endswith("." + domain) for domain in families)
        if host.endswith("ashbyhq.com") and url.netloc == "cdn.ashbyprd.com":
            allowed = url.scheme == "https" and route.request.method == "GET"
        verification_hosts = {"www.recaptcha.net", "www.google.com", "www.gstatic.com", "recaptcha.google.com"}
        if url.netloc in verification_hosts and url.path.startswith(("/recaptcha/", "/recaptcha__")):
            allowed = url.scheme == "https"
        if allowed:
            route.continue_()
        else:
            route.abort()
    context.route("**/*",route_request)

def form_url(url):
    host = urlsplit(url).hostname
    if host == "jobs.ashbyhq.com":
        return url + "/application"
    if host in {"jobs.lever.co","jobs.eu.lever.co"}:
        return url + "/apply"
    return url

def form_fields(page):
    """Read labels and choices as untrusted text, without executing page instructions."""
    fields = []
    radios = {}
    upload = None
    for el in page.locator("input,textarea,select").all():
        meta = el.evaluate("""e => {
          const wrap=e.closest('fieldset, .ashby-application-form-question-entry, .application-question, .field');
          const label=Array.from(e.labels||[]).map(l=>l.innerText).join(' ').trim() || e.getAttribute('aria-label') || '';
          const help=(e.getAttribute('aria-describedby')||'').split(' ').map(id=>document.getElementById(id)?.innerText||'').join(' ');
          return {label, context:wrap?.innerText||help, legend:wrap?.querySelector('legend')?.innerText||'',
            kind:e.type, name:e.name, required:e.required||e.getAttribute('aria-required')==='true'||label.includes('*'),
            options:e.tagName==='SELECT'?Array.from(e.options).filter(o=>!o.disabled&&o.value!=='').map(o=>o.label):[]};
        }""")
        label = " ".join(meta["label"].split())
        kind = meta["kind"]
        if kind == "file":
            if normalized(label) in {"resume","résumé","resume/cv","resume / cv","cv"} or meta["name"] == "resume":
                if upload is not None:
                    raise ReviewNeeded("Multiple resume fields need review.")
                upload = el
            elif meta["required"]:
                raise ReviewNeeded("An additional document is required. Complete this form manually.")
            continue
        if not el.is_visible() or kind in {"submit","button","hidden","reset"}:
            continue
        if kind not in {"text","email","url","tel","textarea","search","number","date","radio","checkbox","select-one"}:
            raise ReviewNeeded("This form uses a control that needs assisted completion.")
        context = " ".join(meta["context"].split())
        if max(len(label), len(context)) > 4000 or len(meta["options"]) > 300:
            raise ReviewNeeded("This question needs assisted review.")
        if not label:
            if meta["name"] in {"name","email"}:
                label = meta["name"]
            else:
                raise ReviewNeeded("An application field has no unambiguous label.")
        spec = {"prompt": label, "context": context, "kind": kind,
                "required": bool(meta["required"]), "options": meta["options"]}
        if kind == "checkbox":
            spec["options"] = ["Yes", "No"]
        if kind == "radio":
            group = meta["name"] or context
            if not group:
                raise ReviewNeeded("Could not identify the radio question.")
            if group not in radios:
                spec["prompt"] = " ".join(meta["legend"].split()) or context
                if not spec["prompt"]:
                    raise ReviewNeeded("Could not identify the radio question.")
                spec["options"] = []
                radios[group] = (spec, [])
                fields.append(radios[group])
            spec, elements = radios[group]
            spec["required"] = spec["required"] or meta["required"]
            spec["options"].append(label)
            elements.append(el)
        else:
            fields.append((spec, [el]))
    keys = [fingerprint(spec) for spec, _ in fields]
    if len(keys) != len(set(keys)):
        raise ReviewNeeded("Duplicate question labels need assisted review.")
    for spec, _ in fields:
        if len(spec["options"]) != len(set(spec["options"])):
            raise ReviewNeeded("Duplicate answer choices need assisted review.")
    return fields, upload


def fill_fields(page, facts):
    fields, upload = form_fields(page)
    supplied, missing, used = set(), [], []
    answers = facts.get("_form_answers", {})
    for spec, elements in fields:
        kind = spec["kind"]
        key = FIELDS.get(normalized(spec["prompt"]))
        if key and facts.get(key) and kind in {"text","email","url","tel","textarea","search"}:
            elements[0].fill(facts[key])
            supplied.add(key)
            continue
        if (kind == "radio" and SPONSORSHIP in normalized(spec["context"])
                and facts.get("requires_sponsorship") is not None
                and {normalized(v) for v in spec["options"]} == {"yes","no"}):
            choice = "yes" if facts["requires_sponsorship"] else "no"
            elements[next(i for i,v in enumerate(spec["options"]) if normalized(v)==choice)].check()
            continue
        identity = fingerprint(spec)
        if identity not in answers:
            missing.append(spec)
            continue
        value = answers[identity]
        if (not value and spec["required"]) or (value and spec["options"] and value not in spec["options"]):
            missing.append(spec)
            continue
        used.append({"question": spec, "answer": value})
        if kind == "radio":
            if value:
                elements[spec["options"].index(value)].check()
        elif kind == "checkbox":
            elements[0].set_checked(value == "Yes")
        elif kind == "select-one":
            if value:
                elements[0].select_option(label=value)
        else:
            elements[0].fill(value)
            if key:
                supplied.add(key)
    if missing:
        raise QuestionsNeeded(missing)
    facts["_used_form_answers"] = used
    return supplied, upload


def fill_and_send(page, snapshot, facts, pdf, before_submit):
    url = form_url(snapshot["url"])
    if sha256(pdf).hexdigest() != snapshot["pdf_sha256"]:
        raise ReviewNeeded("Approved PDF fingerprint changed.")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if page.url.rstrip("/") != url:
        raise ReviewNeeded("The employer redirected the application.")
    page.get_by_role("heading", name=snapshot["role"], exact=True).first.wait_for(timeout=10000)
    submit = page.get_by_role("button", name=re.compile(r"^submit application$", re.I))
    submit.wait_for(timeout=10000)
    if page.locator('iframe[src*="captcha" i]:visible, [data-sitekey]:visible').count():
        raise ReviewNeeded("The employer requires a verification challenge.")
    # Re-read after filling to catch conditional questions revealed by answers.
    for _ in range(3):
        supplied, upload = fill_fields(page, facts)
    name_filled = "full_name" in supplied or {"given_name","family_name"} <= supplied
    if upload is None or "email" not in supplied or not name_filled:
        raise ReviewNeeded("Could not verify the name, email and resume fields.")
    upload.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":pdf})
    fill_fields(page, facts)  # Uploading can reveal extra employer questions too.
    if page.locator("input:invalid:visible,select:invalid:visible,textarea:invalid:visible").count():
        raise ReviewNeeded("An answer failed the employer's validation. Review this form.")
    if page.locator('iframe[src*="bframe"]:visible').count():
        raise ReviewNeeded("The employer requires a verification challenge.")
    if page.url.rstrip("/") != url or page.get_by_text(RECEIPT).count():
        raise ReviewNeeded("The live form changed before submission.")
    before_submit()
    submit.click(timeout=10000)
    success = page.get_by_text(RECEIPT).first
    success.wait_for(state="visible",timeout=20000)
    if urlsplit(page.url).hostname != urlsplit(url).hostname or submit.is_visible():
        raise RuntimeError("Could not verify a terminal confirmation screen.")
    return success.inner_text()[:500]


def submit_hosted(snapshot, facts, pdf, before_submit):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path="/usr/bin/chromium",headless=True,
                                         env={"HOME":"/home/appuser","PATH":"/usr/bin:/bin"})
        context = browser.new_context(service_workers="block",accept_downloads=False)
        guard_routes(context,urlsplit(snapshot["url"]).hostname)
        return fill_and_send(context.new_page(),snapshot,facts,pdf,before_submit)
