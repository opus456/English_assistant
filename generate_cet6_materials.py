from __future__ import annotations

import argparse
import json
import logging
import os
import re
import ssl
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LOGGER = logging.getLogger("cet6_ai_generator")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TODAY_LABEL = date.today().strftime("%m-%d")
TODAY_DIR = f"articles/{TODAY_LABEL}"


@dataclass(slots=True)
class ArticleBundle:
    stem: str
    text_path: Path
    metadata_path: Path
    text: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout_seconds: int
    ssl_context: ssl.SSLContext


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate CET-6 reading materials from scraped articles."
    )
    parser.add_argument("--input-dir", default=TODAY_DIR, help="Directory containing scraped article files.")
    parser.add_argument("--output-dir", default=TODAY_DIR, help="Directory used to store generated files.")
    parser.add_argument("--article-stem", default=None, help="Specific article stem to process, without extension.")
    parser.add_argument(
        "--exercise-type",
        choices=["auto", "multiple_choice", "paragraph_matching"],
        default="auto",
        help="Exercise type. auto alternates based on existing generated files.",
    )
    parser.add_argument("--temperature", type=float, default=0.7, help="Model temperature.")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="HTTP timeout for the LLM request.")
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="Ignore HTTPS certificate errors for the LLM API request.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the LLM call and write sample output files for pipeline validation.",
    )
    parser.add_argument("--env-file", default=".env", help="Environment file used to load API keys and model config.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level.",
    )
    return parser


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def build_ssl_context(ignore_https_errors: bool) -> ssl.SSLContext:
    if ignore_https_errors:
        return ssl._create_unverified_context()

    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile:
        return ssl.create_default_context(cafile=cafile)

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def build_llm_config(args: argparse.Namespace) -> LLMConfig:
    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not api_key:
        raise RuntimeError("Missing API key. Set LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY.")

    base_url = (
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("DEEPSEEK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.deepseek.com/v1"
    ).rstrip("/")
    model = (
        os.environ.get("LLM_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "deepseek-chat"
    )
    return LLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=args.temperature,
        timeout_seconds=args.timeout_seconds,
        ssl_context=build_ssl_context(args.ignore_https_errors),
    )


def load_article_bundle(text_path: Path, metadata_path: Path) -> ArticleBundle:
    return ArticleBundle(
        stem=text_path.stem,
        text_path=text_path,
        metadata_path=metadata_path,
        text=text_path.read_text(encoding="utf-8").strip(),
        metadata=json.loads(metadata_path.read_text(encoding="utf-8")),
    )


def find_article_bundle(input_dir: Path, article_stem: str | None) -> ArticleBundle:
    if article_stem:
        text_path = input_dir / f"{article_stem}.txt"
        metadata_path = input_dir / f"{article_stem}.json"
        if not text_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(f"Missing article files for stem: {article_stem}")
        return load_article_bundle(text_path, metadata_path)

    candidates = sorted(path for path in input_dir.glob("*.txt"))
    if not candidates:
        raise FileNotFoundError(f"No article text files found in {input_dir}")

    latest_text = max(candidates, key=lambda path: path.stat().st_mtime)
    metadata_path = latest_text.with_suffix(".json")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing metadata file for {latest_text.name}")
    return load_article_bundle(latest_text, metadata_path)


def choose_exercise_type(output_dir: Path, requested_type: str) -> str:
    if requested_type != "auto":
        return requested_type

    generated = sorted(output_dir.glob("*_ai_output.json"))
    return "multiple_choice" if len(generated) % 2 == 0 else "paragraph_matching"


def load_prompt_template() -> str:
    prompt_path = Path(__file__).with_name("cet6_generation_prompt.md")
    return prompt_path.read_text(encoding="utf-8").strip()


def slugify_filename(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "cet6-reading"


def split_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def build_pdf_stems(article: ArticleBundle) -> tuple[str, str]:
    article_slug = slugify_filename(article.metadata.get("title", article.stem))
    prefix = f"{TODAY_LABEL}-{article_slug}"
    return f"{prefix}-test", f"{prefix}-answer"


def build_user_prompt(article: ArticleBundle, exercise_type: str) -> str:
    metadata = article.metadata
    return (
        "Generate a CET-6 reading package for the following article.\n\n"
        f"Required exercise type: {exercise_type}\n"
        f"Title: {metadata.get('title', '')}\n"
        f"Source: {metadata.get('source', '')}\n"
        f"Topic: {metadata.get('topic', '')}\n"
        f"Original URL: {metadata.get('url', '')}\n"
        f"Word count: {metadata.get('word_count', '')}\n\n"
        "Article:\n"
        f"{article.text}"
    )


def call_llm(config: LLMConfig, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "temperature": config.temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{config.base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds, context=config.ssl_context) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM request failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    if "choices" not in response_data:
        preview = json.dumps(response_data, ensure_ascii=False)[:500]
        raise RuntimeError(f"Unexpected LLM response structure: {preview}")

    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Unexpected LLM response structure") from exc

    return parse_llm_json(content)


def parse_llm_json(content: str) -> dict[str, Any]:
    content = content.strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("LLM did not return a valid JSON object")
        data = json.loads(content[start : end + 1])

    validate_ai_output(data)
    return data


def validate_ai_output(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise RuntimeError("AI output must be a JSON object")

    for key in ["article_metadata", "exercise", "learning_package"]:
        if key not in data:
            raise RuntimeError(f"AI output missing key: {key}")

    exercise = data["exercise"]
    learning_package = data["learning_package"]
    if not isinstance(exercise.get("questions"), list) or not exercise["questions"]:
        raise RuntimeError("AI output must include non-empty exercise.questions")
    if not isinstance(learning_package.get("vocabulary"), list) or not learning_package["vocabulary"]:
        raise RuntimeError("AI output must include non-empty learning_package.vocabulary")
    if not isinstance(learning_package.get("syntax_analysis"), list) or not learning_package["syntax_analysis"]:
        raise RuntimeError("AI output must include non-empty learning_package.syntax_analysis")


def build_sample_output(article: ArticleBundle, exercise_type: str) -> dict[str, Any]:
    paragraphs = split_paragraphs(article.text)
    metadata = article.metadata

    if exercise_type == "paragraph_matching":
        options = {label: f"Paragraph {label}" for label in ["A", "B", "C", "D", "E", "F", "G", "H"]}
        questions = [
            {
                "id": index + 1,
                "question": statement,
                "options": options,
                "answer": label,
                "explanation": explanation,
            }
            for index, (statement, label, explanation) in enumerate(
                [
                    ("The report argues that convenience is one reason PFAS remain common in daily products.", "F", "文中提到学校制服等产品加入 PFAS 很多时候只是为了便利性，如防污，因此对应这一段。"),
                    ("Some chemicals in the PFAS family are already known to harm human health.", "J", "文章明确指出部分 PFAS 已被证明有毒且致癌，因此该信息对应提到健康风险的段落。"),
                    ("The committee believes monitoring alone is not enough to solve the PFAS problem.", "K", "文章指出委员会批评政府计划过度强调监测，而不是预防或治理污染。"),
                    ("Industry groups warn that a ban may bring unintended practical costs.", "Q", "文中行业团体认为禁用不粘锅中的 PFAS 可能带来更多食物浪费，体现现实代价。"),
                    ("Campaigners believe the UK may lag behind if it does not act as fast as the EU.", "S", "文章指出若英国不采取相同措施，可能落后于欧盟。"),
                    ("PFAS are valuable partly because they resist water, heat, and oil.", "E", "该段集中介绍 PFAS 的性能特点，因此对应此陈述。"),
                    ("The government says it has already started taking strong action on PFAS.", "D", "文章引用政府发言，称其 PFAS 计划显示正在采取果断行动。"),
                    ("The committee proposes removing non-essential PFAS uses from 2027.", "L", "文中明确写到委员会建议自 2027 年起逐步淘汰所有非必要用途。"),
                ]
            )
        ]
    else:
        questions = [
            {
                "id": 1,
                "question": "What is the main purpose of the MPs' recommendation mentioned in the article?",
                "options": {
                    "A": "To expand the industrial use of PFAS in essential sectors",
                    "B": "To prohibit all uses of PFAS immediately without exception",
                    "C": "To phase out non-essential PFAS uses unless they can be justified",
                    "D": "To replace government regulation with voluntary industry action",
                },
                "answer": "C",
                "explanation": "文章核心信息是委员会建议逐步淘汰非必要 PFAS 用途，除非企业能够证明其确有必要或无替代品，因此 C 正确。A 与原文方向相反，B 过度绝对化，D 与文中强调强制规则而非行业自律相矛盾。",
            },
            {
                "id": 2,
                "question": "Why are PFAS called 'forever chemicals'?",
                "options": {
                    "A": "Because they are cheap to manufacture in large quantities",
                    "B": "Because they remain in the environment for a very long time",
                    "C": "Because they are widely used in historical buildings",
                    "D": "Because they can be safely recycled forever",
                },
                "answer": "B",
                "explanation": "文中明确解释 forever chemicals 之所以得名，是因为它们会在生态系统中长期存在并累积，所以 B 正确。A、C、D 都不是命名原因，其中 D 还与原文担忧其难以降解相冲突。",
            },
            {
                "id": 3,
                "question": "What criticism did the committee make of the government's PFAS plan?",
                "options": {
                    "A": "It focuses too much on monitoring instead of prevention and clean-up",
                    "B": "It ignores the needs of the medical sector completely",
                    "C": "It depends too heavily on support from the EU",
                    "D": "It bans PFAS in school uniforms too quickly",
                },
                "answer": "A",
                "explanation": "委员会认为政府计划过度聚焦扩大监测，而不是防止污染和治理污染，因此 A 正确。B、C、D 都不是文章中委员会提出的批评点。",
            },
            {
                "id": 4,
                "question": "Which of the following best reflects the attitude of industry groups toward the proposed ban?",
                "options": {
                    "A": "They fully support it because it will reduce costs",
                    "B": "They oppose it because some applications still bring practical benefits",
                    "C": "They are indifferent because PFAS are no longer profitable",
                    "D": "They welcome it only for medical equipment and firefighting foam",
                },
                "answer": "B",
                "explanation": "行业团体认为全面禁止某些应用并不是正确做法，例如不粘锅禁用后可能导致食物浪费，因此 B 正确。A、C、D 都不符合原文对行业态度的描述。",
            },
        ]

    syntax_source = paragraphs[:3] if len(paragraphs) >= 3 else paragraphs
    return {
        "article_metadata": {
            "title": metadata.get("title", ""),
            "source": metadata.get("source", ""),
            "difficulty": "CET-6",
        },
        "exercise": {
            "type": exercise_type,
            "questions": questions,
        },
        "learning_package": {
            "vocabulary": [
                {"word": "persist", "phonetic": "/pəˈsɪst/", "definition": "持续存在；存留不消失", "example": "Public concern may persist if the pollution problem remains unsolved."},
                {"word": "accumulate", "phonetic": "/əˈkjuːmjəleɪt/", "definition": "积累；堆积", "example": "Toxic substances can accumulate in soil and water over time."},
                {"word": "demonstrate", "phonetic": "/ˈdemənstreɪt/", "definition": "证明；展示", "example": "Manufacturers must demonstrate that safer alternatives are unavailable."},
                {"word": "essential", "phonetic": "/ɪˈsenʃəl/", "definition": "必要的；至关重要的", "example": "Clean drinking water is essential to public health."},
                {"word": "remediation", "phonetic": "/rɪˌmiːdiˈeɪʃən/", "definition": "修复；补救", "example": "The town demanded a remediation plan for the contaminated land."},
                {"word": "disproportionately", "phonetic": "/ˌdɪsprəˈpɔːʃənətli/", "definition": "过度地；不成比例地", "example": "The policy disproportionately affects low-income families."},
                {"word": "phase out", "phonetic": "/feɪz aʊt/", "definition": "逐步淘汰", "example": "The government plans to phase out outdated energy systems."},
                {"word": "carcinogenic", "phonetic": "/ˌkɑːsɪnəˈdʒenɪk/", "definition": "致癌的", "example": "Scientists are studying whether the material is carcinogenic."},
                {"word": "acknowledge", "phonetic": "/əkˈnɒlɪdʒ/", "definition": "承认", "example": "The company acknowledged the risks but defended its product design."},
                {"word": "fall behind", "phonetic": "/fɔːl bɪˈhaɪnd/", "definition": "落后于", "example": "Without innovation, smaller firms may fall behind global competitors."},
            ],
            "syntax_analysis": [
                {
                    "original": syntax_source[0] if syntax_source else article.text[:150],
                    "breakdown": "主干是 School uniforms and non-stick pans are some of the everyday products。that are treated with a group of chemicals 是定语从句，修饰 products；called PFAS 是过去分词短语作补充说明；to make them stain and water resistant 表示目的。",
                    "translation": "校服和不粘锅是日常用品中的一部分，这些产品会经过一类名为 PFAS 的化学物质处理，以使其具备防污和防水性能。",
                },
                {
                    "original": syntax_source[1] if len(syntax_source) > 1 else article.text[:180],
                    "breakdown": "主句是 But there is growing concern。about the long-term environmental and health impacts of some of these 'forever chemicals' 是介词短语说明担忧内容；so called because... 是插入说明，解释其名称来源；because 引导原因状语从句。",
                    "translation": "但是，人们越来越担心其中一些“永久化学物质”带来的长期环境和健康影响，这类物质之所以被这样称呼，是因为它们会在生态系统中持续存在并不断积累。",
                },
                {
                    "original": syntax_source[2] if len(syntax_source) > 2 else article.text[:220],
                    "breakdown": "主句是 A group of MPs has now called for a complete ban on their use。unless 引导条件状语从句；manufacturers can demonstrate 后面省略了 that；they are either essential... or there is no alternative chemical 是并列的表语或存在结构，用来说明例外条件。",
                    "translation": "如今，一组议员呼吁全面禁止使用这类化学物质，除非制造商能够证明，它们对产品而言确属必要，或者根本不存在可替代的化学品。",
                },
            ],
        },
    }


def render_reading_markdown(article: ArticleBundle, ai_output: dict[str, Any]) -> str:
    lines = [
        f"# {article.metadata.get('title', '')}",
        "",
        f"- Source: {article.metadata.get('source', '')}",
        f"- Topic: {article.metadata.get('topic', '')}",
        f"- URL: {article.metadata.get('url', '')}",
        f"- Difficulty: {ai_output['article_metadata'].get('difficulty', 'CET-6')}",
        f"- Exercise Type: {ai_output['exercise'].get('type', '')}",
        "",
        "## Article",
        "",
        article.text,
        "",
        "## Questions",
        "",
    ]

    for question in ai_output["exercise"]["questions"]:
        lines.append(f"### {question['id']}. {question['question']}")
        lines.append("")
        for option_key, option_value in question["options"].items():
            lines.append(f"- {option_key}. {option_value}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_analysis_markdown(article: ArticleBundle, ai_output: dict[str, Any]) -> str:
    lines = [
        f"# {article.metadata.get('title', '')} - Analysis",
        "",
        f"- Source: {article.metadata.get('source', '')}",
        f"- Exercise Type: {ai_output['exercise'].get('type', '')}",
        "",
        "## Answer Key and Explanations",
        "",
    ]

    for question in ai_output["exercise"]["questions"]:
        lines.append(f"### {question['id']}. Answer: {question['answer']}")
        lines.append(question["question"])
        lines.append("")
        lines.append(question["explanation"])
        lines.append("")

    lines.extend(["## Vocabulary", ""])
    for item in ai_output["learning_package"]["vocabulary"]:
        lines.append(f"### {item['word']} {item['phonetic']}")
        lines.append(f"- 释义: {item['definition']}")
        lines.append(f"- 例句: {item['example']}")
        lines.append("")

    lines.extend(["## Syntax Analysis", ""])
    for item in ai_output["learning_package"]["syntax_analysis"]:
        lines.append("### Original")
        lines.append(item["original"])
        lines.append("")
        lines.append("### Breakdown")
        lines.append(item["breakdown"])
        lines.append("")
        lines.append("### Translation")
        lines.append(item["translation"])
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_pdf_css() -> str:
    return """
    @page {
      size: A4;
      margin: 18mm 16mm 20mm 16mm;
    }

    :root {
      --ink: #1a2b3b;
      --muted: #5f7389;
      --line: #d5e2ec;
      --accent: #0f766e;
      --warm: #b45309;
      --warm-soft: #fff7ed;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      color: var(--ink);
      font-family: "Georgia", "Times New Roman", serif;
      font-size: 11pt;
      line-height: 1.7;
      background: linear-gradient(180deg, #ffffff 0%, #f8fbfd 100%);
    }

    .sheet-header {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px 20px 16px;
      margin-bottom: 16px;
      background: linear-gradient(135deg, rgba(238, 247, 255, 0.95), rgba(247, 252, 251, 0.96));
    }

    .analysis-header {
      background: linear-gradient(140deg, rgba(255, 248, 239, 0.96), rgba(245, 251, 255, 0.96));
    }

    .eyebrow {
      font-family: "Helvetica Neue", Arial, sans-serif;
      font-size: 9pt;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 8px;
    }

    h1 {
      margin: 0 0 10px;
      font-size: 21pt;
      line-height: 1.25;
    }

    h2 {
      margin: 20px 0 10px;
      padding-left: 10px;
      border-left: 4px solid var(--accent);
      font-size: 14pt;
      page-break-after: avoid;
    }

    h3 {
      margin: 0 0 8px;
      font-size: 12.2pt;
      line-height: 1.45;
      page-break-after: avoid;
    }

    p {
      margin: 0 0 10px;
      text-align: justify;
    }

    .meta-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 16px;
      font-family: "Helvetica Neue", Arial, sans-serif;
      font-size: 9.4pt;
      color: var(--muted);
    }

    .meta-item {
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.8);
    }

    .lead-box {
      margin-bottom: 18px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.88);
      color: var(--muted);
      font-family: "Helvetica Neue", Arial, sans-serif;
      font-size: 9.6pt;
    }

    .article-body p {
      text-indent: 2em;
    }

    .question-card,
    .answer-card,
    .vocab-card,
    .syntax-card {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px 15px 10px;
      margin-bottom: 12px;
      background: rgba(255, 255, 255, 0.96);
      page-break-inside: avoid;
    }

    .options {
      list-style: none;
      margin: 8px 0 0;
      padding: 0;
      columns: 2;
      column-gap: 18px;
    }

    .options li {
      margin-bottom: 6px;
      break-inside: avoid;
    }

    .answer-space {
      margin-top: 12px;
      height: 32px;
      border-bottom: 1px dashed #b8cad8;
    }

    .answer-chip {
      display: inline-block;
      margin-bottom: 10px;
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--warm-soft);
      color: var(--warm);
      font-family: "Helvetica Neue", Arial, sans-serif;
      font-size: 9pt;
      font-weight: 700;
      letter-spacing: 0.05em;
    }

    .vocab-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .phonetic {
      margin-left: 8px;
      color: var(--muted);
      font-style: italic;
      font-weight: 400;
    }

    .mini-title {
      margin: 10px 0 4px;
      color: var(--muted);
      font-family: "Helvetica Neue", Arial, sans-serif;
      font-size: 9pt;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .footer-note {
      margin-top: 18px;
      text-align: right;
      color: var(--muted);
      font-family: "Helvetica Neue", Arial, sans-serif;
      font-size: 9pt;
    }
    """


def render_reading_html(article: ArticleBundle, ai_output: dict[str, Any]) -> str:
    paragraphs_html = "".join(
        f"<p>{escape(paragraph)}</p>" for paragraph in split_paragraphs(article.text)
    )
    question_blocks = []
    for question in ai_output["exercise"]["questions"]:
        options_html = "".join(
            f"<li><strong>{escape(option_key)}.</strong> {escape(option_value)}</li>"
            for option_key, option_value in question["options"].items()
        )
        question_blocks.append(
            "".join(
                [
                    '<section class="question-card">',
                    f'<div class="question-title">{question["id"]}. {escape(question["question"])}' + '</div>',
                    f'<ul class="options">{options_html}</ul>',
                    '<div class="answer-space"></div>',
                    '</section>',
                ]
            )
        )

    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <title>{escape(article.metadata.get('title', 'CET-6 Reading Test'))}</title>
        <style>{build_pdf_css()}</style>
      </head>
      <body>
        <header class="sheet-header">
          <div class="eyebrow">CET-6 Daily Reading Test</div>
          <h1>{escape(article.metadata.get('title', ''))}</h1>
          <div class="meta-grid">
            <div class="meta-item">Date: {escape(TODAY_LABEL)}</div>
            <div class="meta-item">Source: {escape(article.metadata.get('source', ''))}</div>
            <div class="meta-item">Topic: {escape(article.metadata.get('topic', ''))}</div>
            <div class="meta-item">Type: {escape(ai_output['exercise'].get('type', ''))}</div>
          </div>
        </header>
        <section class="lead-box">Read the following article carefully and answer the questions below. The layout leaves enough whitespace for tablet handwriting and annotations.</section>
        <section>
          <h2>Article</h2>
          <div class="article-body">{paragraphs_html}</div>
        </section>
        <section>
          <h2>Questions</h2>
          {''.join(question_blocks)}
        </section>
        <div class="footer-note">Generated by CET6 Daily Flow</div>
      </body>
    </html>
    """


def render_analysis_html(article: ArticleBundle, ai_output: dict[str, Any]) -> str:
    answer_cards = []
    for question in ai_output["exercise"]["questions"]:
        answer_cards.append(
            "".join(
                [
                    '<section class="answer-card">',
                    f'<div class="answer-chip">Answer {escape(str(question["answer"]))}</div>',
                    f'<div class="answer-title">{question["id"]}. {escape(question["question"])}' + '</div>',
                    f'<p>{escape(question["explanation"])}</p>',
                    '</section>',
                ]
            )
        )

    vocab_cards = []
    for item in ai_output["learning_package"]["vocabulary"]:
        vocab_cards.append(
            "".join(
                [
                    '<section class="vocab-card">',
                    f'<div class="vocab-word">{escape(item["word"])}<span class="phonetic">{escape(item["phonetic"])}' + '</span></div>',
                    f'<p><strong>释义：</strong>{escape(item["definition"])}</p>',
                    f'<p><strong>例句：</strong>{escape(item["example"])}</p>',
                    '</section>',
                ]
            )
        )

    syntax_cards = []
    for item in ai_output["learning_package"]["syntax_analysis"]:
        syntax_cards.append(
            "".join(
                [
                    '<section class="syntax-card">',
                    '<div class="mini-title">Original</div>',
                    f'<p>{escape(item["original"])}</p>',
                    '<div class="mini-title">Breakdown</div>',
                    f'<p>{escape(item["breakdown"])}</p>',
                    '<div class="mini-title">Translation</div>',
                    f'<p>{escape(item["translation"])}</p>',
                    '</section>',
                ]
            )
        )

    return f"""
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8">
        <title>{escape(article.metadata.get('title', 'CET-6 Reading Analysis'))}</title>
        <style>{build_pdf_css()}</style>
      </head>
      <body>
        <header class="sheet-header analysis-header">
          <div class="eyebrow">CET-6 Daily Reading Answer Sheet</div>
          <h1>{escape(article.metadata.get('title', ''))}</h1>
          <div class="meta-grid">
            <div class="meta-item">Date: {escape(TODAY_LABEL)}</div>
            <div class="meta-item">Source: {escape(article.metadata.get('source', ''))}</div>
            <div class="meta-item">Word Count: {escape(str(article.metadata.get('word_count', '')))}</div>
            <div class="meta-item">Difficulty: {escape(ai_output['article_metadata'].get('difficulty', 'CET-6'))}</div>
          </div>
        </header>
        <section>
          <h2>Answer Key and Explanation</h2>
          {''.join(answer_cards)}
        </section>
        <section>
          <h2>High-Frequency Vocabulary</h2>
          <div class="vocab-grid">{''.join(vocab_cards)}</div>
        </section>
        <section>
          <h2>Complex Sentence Analysis</h2>
          {''.join(syntax_cards)}
        </section>
        <div class="footer-note">Generated by CET6 Daily Flow</div>
      </body>
    </html>
    """


def render_pdfs_with_reportlab(
    output_dir: Path, article: ArticleBundle, ai_output: dict[str, Any]
) -> tuple[Path, Path]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError(
            "Missing PDF dependency. Install reportlab to enable the PDF fallback renderer."
        ) from exc

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    test_stem, answer_stem = build_pdf_stems(article)
    test_pdf_path = output_dir / f"{test_stem}.pdf"
    answer_pdf_path = output_dir / f"{answer_stem}.pdf"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExamTitle",
        parent=styles["Title"],
        fontName="STSong-Light",
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#17324d"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "ExamSubtitle",
        parent=styles["Normal"],
        fontName="STSong-Light",
        fontSize=9.5,
        leading=13,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#557086"),
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "Heading",
        parent=styles["Heading2"],
        fontName="STSong-Light",
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#0f766e"),
        spaceBefore=10,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=16,
        alignment=TA_JUSTIFY,
        textColor=colors.HexColor("#1f2f3d"),
        spaceAfter=6,
    )
    card_title_style = ParagraphStyle(
        "CardTitle",
        parent=body_style,
        fontName="STSong-Light",
        fontSize=11,
        leading=16,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#17324d"),
        spaceAfter=6,
    )
    answer_style = ParagraphStyle(
        "Answer",
        parent=body_style,
        textColor=colors.HexColor("#9a3412"),
    )

    def build_meta_table() -> Table:
        data = [
            [
                f"Date: {TODAY_LABEL}",
                f"Source: {article.metadata.get('source', '')}",
            ],
            [
                f"Topic: {article.metadata.get('topic', '')}",
                f"Type: {ai_output['exercise'].get('type', '')}",
            ],
        ]
        table = Table(data, colWidths=[85 * mm, 85 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#557086")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7fbfc")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c7d7e2")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dbe6ee")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return table

    def build_card(content: list[Any], accent: str = "#d8e5ec") -> Table:
        table = Table([[item] for item in content], colWidths=[180 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(accent)),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return table

    def build_test_story() -> list[Any]:
        story: list[Any] = [
            Paragraph("CET-6 Daily Reading Test", title_style),
            Paragraph(escape(article.metadata.get("title", "")), subtitle_style),
            build_meta_table(),
            Spacer(1, 6 * mm),
            Paragraph("Article", heading_style),
        ]
        for paragraph in split_paragraphs(article.text):
            story.append(Paragraph(escape(paragraph), body_style))
        story.extend([Spacer(1, 4 * mm), Paragraph("Questions", heading_style)])

        for question in ai_output["exercise"]["questions"]:
            card_content: list[Any] = [
                Paragraph(
                    f"{question['id']}. {escape(question['question'])}",
                    card_title_style,
                )
            ]
            for option_key, option_value in question["options"].items():
                card_content.append(
                    Paragraph(
                        f"{escape(option_key)}. {escape(option_value)}",
                        body_style,
                    )
                )
            card_content.append(
                Paragraph("Answer: ________________________________", body_style)
            )
            story.append(build_card(card_content))
            story.append(Spacer(1, 3 * mm))

        return story

    def build_answer_story() -> list[Any]:
        story: list[Any] = [
            Paragraph("CET-6 Daily Reading Answer Sheet", title_style),
            Paragraph(escape(article.metadata.get("title", "")), subtitle_style),
            build_meta_table(),
            Spacer(1, 6 * mm),
            Paragraph("Answer Key and Explanation", heading_style),
        ]

        for question in ai_output["exercise"]["questions"]:
            story.append(
                build_card(
                    [
                        Paragraph(
                            f"{question['id']}. {escape(question['question'])}",
                            card_title_style,
                        ),
                        Paragraph(f"Answer: {escape(str(question['answer']))}", answer_style),
                        Paragraph(escape(question["explanation"]), body_style),
                    ],
                    accent="#f1d7c7",
                )
            )
            story.append(Spacer(1, 3 * mm))

        story.extend([Spacer(1, 2 * mm), Paragraph("High-Frequency Vocabulary", heading_style)])
        for item in ai_output["learning_package"]["vocabulary"]:
            story.append(
                build_card(
                    [
                        Paragraph(
                            escape(f"{item['word']}  {item['phonetic']}"),
                            card_title_style,
                        ),
                        Paragraph(escape(f"释义：{item['definition']}"), body_style),
                        Paragraph(escape(f"例句：{item['example']}"), body_style),
                    ]
                )
            )
            story.append(Spacer(1, 2.5 * mm))

        story.extend([Spacer(1, 2 * mm), Paragraph("Complex Sentence Analysis", heading_style)])
        for item in ai_output["learning_package"]["syntax_analysis"]:
            story.append(
                build_card(
                    [
                        Paragraph("Original", card_title_style),
                        Paragraph(escape(item["original"]), body_style),
                        Paragraph("Breakdown", card_title_style),
                        Paragraph(escape(item["breakdown"]), body_style),
                        Paragraph("Translation", card_title_style),
                        Paragraph(escape(item["translation"]), body_style),
                    ]
                )
            )
            story.append(Spacer(1, 3 * mm))

        return story

    def on_page(canvas, doc) -> None:
        canvas.setFont("STSong-Light", 9)
        canvas.setFillColor(colors.HexColor("#6b7f90"))
        canvas.drawRightString(doc.pagesize[0] - 16 * mm, 10 * mm, f"Page {doc.page}")
        canvas.drawString(16 * mm, 10 * mm, "Generated by CET6 Daily Flow")

    test_doc = SimpleDocTemplate(
        str(test_pdf_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        title=article.metadata.get("title", "CET-6 Daily Reading Test"),
    )
    answer_doc = SimpleDocTemplate(
        str(answer_pdf_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        title=article.metadata.get("title", "CET-6 Daily Reading Answer Sheet"),
    )
    test_doc.build(build_test_story(), onFirstPage=on_page, onLaterPages=on_page)
    answer_doc.build(build_answer_story(), onFirstPage=on_page, onLaterPages=on_page)
    return test_pdf_path, answer_pdf_path


def render_pdfs(output_dir: Path, article: ArticleBundle, ai_output: dict[str, Any]) -> tuple[Path, Path]:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        LOGGER.warning("WeasyPrint is unavailable, falling back to reportlab: %s", exc)
        return render_pdfs_with_reportlab(output_dir, article, ai_output)

    test_stem, answer_stem = build_pdf_stems(article)
    test_pdf_path = output_dir / f"{test_stem}.pdf"
    answer_pdf_path = output_dir / f"{answer_stem}.pdf"

    try:
        HTML(string=render_reading_html(article, ai_output), base_url=str(output_dir.resolve())).write_pdf(test_pdf_path)
        HTML(string=render_analysis_html(article, ai_output), base_url=str(output_dir.resolve())).write_pdf(answer_pdf_path)
        return test_pdf_path, answer_pdf_path
    except OSError as exc:
        LOGGER.warning("WeasyPrint failed due to missing system libraries: %s", exc)
        return render_pdfs_with_reportlab(output_dir, article, ai_output)


def write_outputs(output_dir: Path, article: ArticleBundle, ai_output: dict[str, Any]) -> tuple[Path, Path, Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{article.stem}_ai_output.json"
    reading_path = output_dir / f"{article.stem}_reading.md"
    analysis_path = output_dir / f"{article.stem}_analysis.md"

    json_path.write_text(json.dumps(ai_output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reading_path.write_text(render_reading_markdown(article, ai_output), encoding="utf-8")
    analysis_path.write_text(render_analysis_markdown(article, ai_output), encoding="utf-8")
    test_pdf_path, answer_pdf_path = render_pdfs(output_dir, article, ai_output)
    return json_path, reading_path, analysis_path, test_pdf_path, answer_pdf_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    load_env_file(Path(args.env_file))

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    article = find_article_bundle(input_dir, args.article_stem)
    exercise_type = choose_exercise_type(output_dir, args.exercise_type)
    LOGGER.info("Using article %s", article.text_path.name)
    LOGGER.info("Selected exercise type: %s", exercise_type)

    if args.dry_run:
        ai_output = build_sample_output(article, exercise_type)
    else:
        config = build_llm_config(args)
        ai_output = call_llm(
            config,
            system_prompt=load_prompt_template(),
            user_prompt=build_user_prompt(article, exercise_type),
        )

    json_path, reading_path, analysis_path, test_pdf_path, answer_pdf_path = write_outputs(output_dir, article, ai_output)
    LOGGER.info("Saved AI JSON to %s", json_path)
    LOGGER.info("Saved reading paper to %s", reading_path)
    LOGGER.info("Saved analysis paper to %s", analysis_path)
    LOGGER.info("Saved test PDF to %s", test_pdf_path)
    LOGGER.info("Saved answer PDF to %s", answer_pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
