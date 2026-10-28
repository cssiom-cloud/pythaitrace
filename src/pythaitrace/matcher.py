"""
PyThaiTrace v2.0 - 3-Tier Matcher Engine & Universal Fallback (matcher.py)
Hierarchical diagnostic matching engine resolving exceptions through:
- Tier 1: Strict regex with named capture groups
- Tier 2: Loose/fuzzy token matching for Python version message variants
- Tier 3: Class-level generic fallback for standard exception types
- Universal __FALLBACK__: Introspective safety net for 3rd-party/custom exceptions
"""

from __future__ import annotations
import inspect
import json
from pathlib import Path
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from pythaitrace.models import (
    ExplanationCard,
    KnowledgeRule,
    MatchResult,
    NormalizedTraceback,
)

# Built-in in-memory fallback rule in case rules.json is missing or corrupted
DEFAULT_FALLBACK_RULE = KnowledgeRule(
    error_id="__FALLBACK__",
    exception_class="__FALLBACK__",
    pattern=None,
    summary_th="ตรวจพบข้อผิดพลาดเฉพาะทาง: {exception_module}.{exception_class}",
    mental_model_th=(
        "ข้อผิดพลาดนี้ไม่ได้เกิดจากไวยากรณ์พื้นฐานทั่วไปของภาษา Python "
        "แต่เป็นข้อยกเว้นเฉพาะของไลบรารีภายนอก ({exception_module}) หรือโค้ดที่สร้างขึ้นเอง "
        "ซึ่งมีเงื่อนไขการทำงานเฉพาะของแพ็กเกจนั้นๆ ที่ไม่เป็นไปตามข้อตกลง"
    ),
    fix_suggestions_th=[
        "อ่านคำอธิบายใน Docstring ด้านบนเพื่อทำความเข้าใจเงื่อนไขของข้อผิดพลาด",
        "ตรวจสอบเอกสารคู่มือของไลบรารี '{exception_module}' เกี่ยวกับข้อผิดพลาดนี้",
        "ตรวจสอบพารามิเตอร์และอาร์กิวเมนต์ที่ส่งเข้าไปในฟังก์ชันของไลบรารีว่าถูกต้องครบถ้วน",
        "ค้นหาแนวทางแก้ไขจากลิงก์ Google หรือ StackOverflow ด้านล่าง",
    ],
    search_keywords="python {exception_class}",
)

# Standard generic rules for built-in exceptions not covered in rules.json
STANDARD_BUILTIN_GENERICS: Dict[str, Dict[str, Any]] = {
    "ConnectionError": {
        "error_id": "connection_generic",
        "summary_th": "ไม่สามารถสร้างหรือรักษาการเชื่อมต่อกับระบบเครือข่ายหรือเซิร์ฟเวอร์ปลายทางได้",
        "mental_model_th": (
            "เหมือนเราพยายามโทรศัพท์ไปหาเพื่อน แต่ปลายสายปิดเครื่อง สายหลุด หรือไม่มีสัญญาณเครือข่าย "
            "Python ไม่สามารถส่งผ่านข้อมูลไปยังที่อยู่ IP หรือ Port ที่ระบุได้"
        ),
        "fix_suggestions_th": [
            "ตรวจสอบว่าอินเทอร์เน็ตหรือระบบเครือข่ายสามารถเข้าถึงเซิร์ฟเวอร์เป้าหมายได้ตามปกติ",
            "ตรวจสอบ Hostname, IP Address และ Port ว่าระบุถูกต้องหรือไม่",
            "ตรวจสอบว่าเซิร์ฟเวอร์ปลายทางเปิดให้บริการอยู่หรือไม่ และไม่มี Firewall บล็อกการเชื่อมต่อ",
        ],
        "search_keywords": "python ConnectionError",
    },
    "FileNotFoundError": {
        "error_id": "file_not_found_generic",
        "summary_th": "ค้นหาไฟล์หรือไดเรกทอรีที่ระบุไม่พบบนระบบไฟล์",
        "mental_model_th": (
            "เหมือนสั่งให้เปิดแฟ้มเอกสารในตู้ แต่ในตู้นั้นไม่มีแฟ้มชื่อนี้วางอยู่เลย "
            "อาจระบุพาธผิด หรือโปรแกรมทำงานอยู่ในโฟลเดอร์ทำงานคนละจุดกับที่ไฟล์จริงตั้งอยู่"
        ),
        "fix_suggestions_th": [
            "ตรวจสอบว่าไฟล์เป้าหมายมีอยู่จริงตามเส้นทาง (Path) นั้นหรือไม่",
            "ระวังความแตกต่างของ Working Directory ปัจจุบัน (Current Working Directory)",
            "แนะนำให้ใช้พาธแบบสัมบูรณ์ (Absolute Path) หรือใช้ pathlib.Path(__file__).parent",
        ],
        "search_keywords": "python FileNotFoundError",
    },
    "RecursionError": {
        "error_id": "recursion_generic",
        "summary_th": "การเรียกใช้ฟังก์ชันตัวเองซ้ำ (Recursion) เกินขีดจำกัดความลึกสูงสุดของระบบ",
        "mental_model_th": (
            "เหมือนการวางกระจกเงา 2 บานส่องหากัน ทำให้เกิดภาพสะท้อนไม่รู้จบ "
            "ฟังก์ชันเรียกตัวเองซ้ำไปเรื่อยๆ โดยไม่มีจุดหยุด (Base Case) จนหน่วยความจำ Stack เต็ม"
        ),
        "fix_suggestions_th": [
            "ตรวจสอบเงื่อนไขหยุดการเรียกซ้ำ (Base Case) ในฟังก์ชัน Recursion",
            "ตรวจสอบว่าพารามิเตอร์ที่ส่งเข้าไปในรอบถัดไปมีการขยับเข้าใกล้ Base Case หรือไม่",
            "พิจารณาเปลี่ยนอัลกอริทึมจากการเรียกซ้ำมาเป็นการวนลูปปกติ (Iterative loop)",
        ],
        "search_keywords": "python RecursionError maximum recursion depth exceeded",
    },
    "TimeoutError": {
        "error_id": "timeout_generic",
        "summary_th": "การดำเนินการเกินระยะเวลาที่กำหนดไว้ (Timeout) ก่อนที่กระบวนการจะสำเร็จ",
        "mental_model_th": (
            "เหมือนการรอต่อคิวซื้อของที่กำหนดเวลารอไว้สูงสุด แต่เมื่อหมดเวลาที่กำหนดแล้วยังไม่ถึงคิว "
            "ระบบจึงตัดการทำงานเพื่อป้องกันไม่ให้โปรแกรมค้างอยู่อย่างไม่มีที่สิ้นสุด"
        ),
        "fix_suggestions_th": [
            "ตรวจสอบการตอบสนองของบริการหรือกระบวนการปลายทางว่าทำงานช้าผิดปกติหรือไม่",
            "พิจารณาขยายค่า Timeout ให้เหมาะสมกับขนาดข้อมูลหรือความเร็วเครือข่าย",
            "ครอบด้วยบล็อก try...except TimeoutError เพื่อให้ระบบมีแผนสำรองในการทำงานต่อ",
        ],
        "search_keywords": "python TimeoutError",
    },
    "RuntimeError": {
        "error_id": "runtime_generic",
        "summary_th": "เกิดข้อผิดพลาดในการประมวลผลขณะโปรแกรมกำลังทำงาน โดยไม่ตรงกับประเภทข้อผิดพลาดอื่นที่เฉพาะเจาะจง",
        "mental_model_th": (
            "เป็นข้อผิดพลาดระดับสถานะการทำงาน (Runtime State) เช่น มีการแก้ไขข้อมูลในดิกชันนารีขณะกำลังวนลูปอยู่ "
            "หรือมีเธรดทำงานขัดแย้งกัน"
        ),
        "fix_suggestions_th": [
            "ตรวจสอบสถานะการทำงานของโปรแกรมในบรรทัดที่เกิดข้อผิดพลาด",
            "หากเกิดข้อผิดพลาดขณะวนลูป เช่น dictionary changed size during iteration ให้วนลูปผ่านสำเนาแทน เช่น list(d.keys())",
            "ตรวจสอบการจัดการเธรดและการซิงโครไนซ์ข้อมูล",
        ],
        "search_keywords": "python RuntimeError",
    },
}


def safe_format(template: str, params: Dict[str, Any]) -> str:
    """
    Safely interpolates placeholders in template strings.
    If a placeholder key is missing, replaces with '<key>' without raising KeyError.
    If template contains formatting syntax errors, returns original template string.
    """
    if not template:
        return ""

    class SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return f"<{key}>"

    try:
        clean_params = {str(k): str(v) for k, v in params.items()}
        return template.format_map(SafeDict(clean_params))
    except Exception:
        return template


def build_search_urls(query: str) -> Tuple[str, str]:
    """
    Constructs percent-encoded Google and StackOverflow search URLs.
    Truncates query to at most 500 characters to prevent HTTP 414 URI Too Long.
    """
    clean_query = query.strip()
    if len(clean_query) > 500:
        clean_query = clean_query[:500]
    google_params = urllib.parse.urlencode({"q": clean_query})
    google_url = f"https://www.google.com/search?{google_params}"

    so_params = urllib.parse.urlencode({"q": f"[python] {clean_query}"})
    so_url = f"https://stackoverflow.com/search?{so_params}"

    return google_url, so_url


class MatcherEngine:
    """
    3-Tier Exception Matcher Engine.
    Evaluates:
      1. Tier 1: Strict regex matching with named capture groups.
      2. Tier 2: Loose/fuzzy token matching for version variants.
      3. Tier 3: Class generic fallback matching exception class name.
      4. Tier 4 / Universal Fallback: Introspective explanation for 3rd-party/custom exceptions.
    """

    def __init__(self, rules_path: Optional[str] = None):
        self.rules: List[KnowledgeRule] = []
        self._compiled_rules: List[Tuple[KnowledgeRule, Optional[re.Pattern]]] = []
        self._rules_by_class: Dict[str, List[Tuple[KnowledgeRule, Optional[re.Pattern]]]] = {}
        self._fallback_rule: KnowledgeRule = DEFAULT_FALLBACK_RULE

        self._load_rules(rules_path)

    def _resolve_rules_path(self, custom_path: Optional[str]) -> Optional[Path]:
        if custom_path:
            p = Path(custom_path)
            if p.is_file():
                return p

        # Check relative to package location
        candidates = [
            Path(__file__).parent / "rules.json",
            Path(__file__).resolve().parent.parent / "pythaitrace" / "rules.json",
            Path.cwd() / "src" / "pythaitrace" / "rules.json",
            Path.cwd() / "rules.json",
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _load_rules(self, rules_path: Optional[str]) -> None:
        target_path = self._resolve_rules_path(rules_path)
        raw_rules: List[Dict[str, Any]] = []

        if target_path and target_path.is_file():
            try:
                with open(target_path, "r", encoding="utf-8-sig") as f:
                    raw_rules = json.load(f)
            except Exception:
                raw_rules = []

        for item in raw_rules:
            try:
                rule = KnowledgeRule(**item)
                pattern_re: Optional[re.Pattern] = None
                if rule.pattern:
                    try:
                        pattern_re = re.compile(rule.pattern)
                    except re.error:
                        pattern_re = None

                self.rules.append(rule)
                self._compiled_rules.append((rule, pattern_re))

                cls_name = rule.exception_class
                if cls_name not in self._rules_by_class:
                    self._rules_by_class[cls_name] = []
                self._rules_by_class[cls_name].append((rule, pattern_re))

                if cls_name == "__FALLBACK__":
                    self._fallback_rule = rule
            except Exception:
                continue

        # If rules list was empty, ensure fallback rule is available
        if not self.rules:
            self.rules.append(DEFAULT_FALLBACK_RULE)
            self._compiled_rules.append((DEFAULT_FALLBACK_RULE, None))
            self._fallback_rule = DEFAULT_FALLBACK_RULE

    def match(
        self,
        norm_tb: NormalizedTraceback,
        exc: Optional[BaseException] = None,
    ) -> ExplanationCard:
        """
        Executes 3-tier cascade matching on NormalizedTraceback, producing
        an ExplanationCard for terminal rendering.
        """
        match_result = self._evaluate_cascade(norm_tb, exc)
        return self._synthesize_card(norm_tb, match_result, exc)

    def _evaluate_cascade(
        self,
        norm_tb: NormalizedTraceback,
        exc: Optional[BaseException] = None,
    ) -> MatchResult:
        exc_type = norm_tb.exc_type_name
        msg = norm_tb.exc_message

        # ------------------------------------------------------------------
        # Tier 1: Strict Regex Match
        # ------------------------------------------------------------------
        class_candidates = self._rules_by_class.get(exc_type, [])
        for rule, pattern_re in class_candidates:
            if pattern_re is not None:
                m = pattern_re.search(msg)
                if m:
                    extracted = {k: v for k, v in m.groupdict().items() if v is not None}
                    return MatchResult(
                        rule=rule,
                        tier=1,
                        extracted_entities=extracted,
                    )

        # ------------------------------------------------------------------
        # Tier 2: Loose / Fuzzy Token Match
        # ------------------------------------------------------------------
        tier2_result = self._match_tier2_fuzzy(norm_tb)
        if tier2_result is not None:
            return tier2_result

        # ------------------------------------------------------------------
        # Tier 3: Class-Level Generic Fallback
        # ------------------------------------------------------------------
        for rule, pattern_re in class_candidates:
            if pattern_re is None and rule.pattern is None:
                return MatchResult(
                    rule=rule,
                    tier=3,
                    extracted_entities={},
                )

        # Check standard built-in generic fallback dictionary
        if exc_type in STANDARD_BUILTIN_GENERICS:
            data = STANDARD_BUILTIN_GENERICS[exc_type]
            synth_rule = KnowledgeRule(
                error_id=data["error_id"],
                exception_class=exc_type,
                pattern=None,
                summary_th=data["summary_th"],
                mental_model_th=data["mental_model_th"],
                fix_suggestions_th=data["fix_suggestions_th"],
                search_keywords=data["search_keywords"],
            )
            return MatchResult(
                rule=synth_rule,
                tier=3,
                extracted_entities={},
            )

        # ------------------------------------------------------------------
        # Tier 4: Universal Fallback (__FALLBACK__)
        # ------------------------------------------------------------------
        return MatchResult(
            rule=self._fallback_rule,
            tier=4,
            extracted_entities={},
        )

    def _match_tier2_fuzzy(self, norm_tb: NormalizedTraceback) -> Optional[MatchResult]:
        """
        Extracts quoted identifiers and keyword signatures when message wording
        varies across Python versions.
        """
        exc_type = norm_tb.exc_type_name
        msg = norm_tb.exc_message
        msg_lower = msg.lower()

        # Extract quoted substrings
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", msg)

        # Helper to get specific rule by error_id
        def get_rule_by_id(error_id: str) -> Optional[KnowledgeRule]:
            for r, _ in self._compiled_rules:
                if r.error_id == error_id:
                    return r
            return None

        if exc_type == "NameError":
            if "defined" in msg_lower or quoted:
                var_name = quoted[0] if quoted else (msg.split()[-1] if msg.split() else "")
                rule = get_rule_by_id("name_not_defined")
                if rule:
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"var": var_name},
                    )

        elif exc_type == "AttributeError":
            if "attribute" in msg_lower or quoted:
                rule = get_rule_by_id("attr_has_no_attribute")
                if rule:
                    if len(quoted) >= 2:
                        return MatchResult(
                            rule=rule,
                            tier=2,
                            extracted_entities={"type": quoted[0], "attr": quoted[1]},
                        )
                    elif len(quoted) == 1:
                        return MatchResult(
                            rule=rule,
                            tier=2,
                            extracted_entities={"type": "object", "attr": quoted[0]},
                        )

        elif exc_type == "KeyError":
            rule = get_rule_by_id("key_not_found")
            if rule:
                key_val = quoted[0] if quoted else msg.strip()
                return MatchResult(
                    rule=rule,
                    tier=2,
                    extracted_entities={"key": key_val},
                )

        elif exc_type == "ModuleNotFoundError":
            if "module" in msg_lower or quoted:
                rule = get_rule_by_id("module_not_found")
                if rule:
                    mod_name = quoted[0] if quoted else (msg.split()[-1] if msg.split() else "")
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"module": mod_name},
                    )

        elif exc_type == "IndexError":
            if "range" in msg_lower or "index" in msg_lower:
                rule = get_rule_by_id("index_out_of_range")
                if rule:
                    seq_type = quoted[0] if quoted else "sequence"
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"type": seq_type},
                    )

        elif exc_type == "ZeroDivisionError":
            if "zero" in msg_lower:
                rule = get_rule_by_id("zero_division")
                if rule:
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={},
                    )

        elif exc_type == "TypeError":
            if "unsupported" in msg_lower or "operand" in msg_lower:
                rule = get_rule_by_id("type_unsupported_operand")
                if rule:
                    t1 = quoted[0] if len(quoted) > 0 else "type1"
                    t2 = quoted[1] if len(quoted) > 1 else "type2"
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"type1": t1, "type2": t2, "op": "operation"},
                    )
            elif "callable" in msg_lower:
                rule = get_rule_by_id("type_not_callable")
                if rule:
                    t = quoted[0] if quoted else "object"
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"type": t},
                    )
            elif "subscriptable" in msg_lower:
                rule = get_rule_by_id("type_not_subscriptable")
                if rule:
                    t = quoted[0] if quoted else "object"
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"type": t},
                    )
            elif "unpack" in msg_lower:
                rule = get_rule_by_id("type_unpack_non_iterable")
                if rule:
                    t = quoted[0] if quoted else "object"
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"type": t},
                    )

        elif exc_type == "ValueError":
            if "float" in msg_lower or "convert" in msg_lower:
                rule = get_rule_by_id("value_invalid_literal_float")
                if rule:
                    val = quoted[0] if quoted else ""
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"value": val},
                    )
            elif "int" in msg_lower or "base" in msg_lower:
                rule = get_rule_by_id("value_invalid_literal_int")
                if rule:
                    val = quoted[0] if quoted else ""
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={"value": val, "base": "10"},
                    )
            elif "unpack" in msg_lower:
                rule = get_rule_by_id("value_unpack_mismatch")
                if rule:
                    return MatchResult(
                        rule=rule,
                        tier=2,
                        extracted_entities={},
                    )

        return None

    def _get_clean_docstring(
        self,
        exc: Optional[BaseException],
        norm_tb: NormalizedTraceback,
    ) -> Optional[str]:
        """
        Extracts a clean, non-inherited docstring for the exception.
        Ensures non-string docstrings and inherited builtins.Exception docstrings are ignored.
        """
        doc: Any = None
        if exc is not None:
            cls = exc.__class__
            try:
                # Check class's own __dict__ first to prevent crawling MRO to builtins.Exception
                if hasattr(cls, "__dict__") and "__doc__" in cls.__dict__:
                    doc = cls.__dict__["__doc__"]
                elif cls.__module__ == "builtins":
                    doc = getattr(cls, "__doc__", None)
                else:
                    doc = None
            except Exception:
                doc = None

            if doc is not None:
                if not isinstance(doc, str):
                    return None
                cleaned = inspect.cleandoc(doc).strip()
                base_docs = {
                    inspect.getdoc(Exception),
                    inspect.getdoc(BaseException),
                    getattr(Exception, "__doc__", None),
                    getattr(BaseException, "__doc__", None),
                }
                if cls not in (Exception, BaseException) and cleaned in base_docs:
                    return None
                return cleaned if cleaned else None
            return None

        if norm_tb.docstring and isinstance(norm_tb.docstring, str):
            cleaned = norm_tb.docstring.strip()
            return cleaned if cleaned else None

        return None

    def _synthesize_card(
        self,
        norm_tb: NormalizedTraceback,
        result: MatchResult,
        exc: Optional[BaseException] = None,
    ) -> ExplanationCard:
        rule = result.rule
        entities = dict(result.extracted_entities)

        is_fallback = result.tier == 4 or rule.exception_class == "__FALLBACK__"

        # Determine module and class names
        exc_class = norm_tb.exc_type_name
        if exc is not None:
            exc_module = (
                getattr(exc.__class__, "__module__", None)
                or norm_tb.exception_module
                or "builtins"
            )
        else:
            exc_module = norm_tb.exception_module or "builtins"

        # Pass module and class into entities for formatting
        entities["exception_class"] = exc_class
        entities["exception_module"] = exc_module

        # Error ID assignment
        if is_fallback:
            error_id = "__FALLBACK__"
            title_th = f"พบข้อผิดพลาดที่ไม่คุ้นเคย: {exc_class}"
        else:
            error_id = rule.error_id.upper()
            title_th = f"พบข้อผิดพลาด: {exc_class}"

        # Docstring extraction
        docstring = self._get_clean_docstring(exc, norm_tb)

        # Format texts with safe_format
        summary_th = safe_format(rule.summary_th, entities)
        mental_model_th = safe_format(rule.mental_model_th, entities)
        fix_suggestions_th = [safe_format(s, entities) for s in rule.fix_suggestions_th]

        # Context retention: Introspect __cause__ or __context__ if present
        cause_extra = ""
        if exc is not None:
            visited = set()
            chain: List[BaseException] = []
            curr: Optional[BaseException] = getattr(exc, "__cause__", None)
            if curr is None and not getattr(exc, "__suppress_context__", False):
                curr = getattr(exc, "__context__", None)

            while curr is not None and id(curr) not in visited:
                visited.add(id(curr))
                chain.append(curr)
                next_cause = getattr(curr, "__cause__", None)
                if next_cause is None and not getattr(curr, "__suppress_context__", False):
                    next_cause = getattr(curr, "__context__", None)
                curr = next_cause

            if chain:
                direct_cause = chain[0]
                direct_type = type(direct_cause).__name__
                try:
                    direct_msg = str(direct_cause).strip()
                except Exception:
                    direct_msg = f"<{direct_type}>"

                cause_extra = f"{direct_type} {direct_msg}".strip() if direct_msg else direct_type
                if len(cause_extra) > 200:
                    cause_extra = cause_extra[:200]

                fix_suggestions_th.append(
                    f"ตรวจสอบสาเหตุตั้งต้น (Chained Cause): {direct_type}{(' ' + direct_msg) if direct_msg else ''}"
                )

                if len(chain) > 1:
                    root_cause = chain[-1]
                    root_type = type(root_cause).__name__
                    try:
                        root_msg = str(root_cause).strip()
                    except Exception:
                        root_msg = f"<{root_type}>"
                    fix_suggestions_th.append(
                        f"ต้นตอแรกสุด (Root Cause): {root_type}{(' ' + root_msg) if root_msg else ''}"
                    )

        # Search keywords compilation
        if is_fallback:
            msg_part = norm_tb.exc_message[:500] if len(norm_tb.exc_message) > 500 else norm_tb.exc_message
            search_keywords = f"python {exc_class} {msg_part}".strip()
        else:
            search_keywords = safe_format(rule.search_keywords, entities).strip()
            # Ensure captured key entities are included in keywords if not already present
            for k in ["var", "key", "module", "attr", "type", "value", "func"]:
                if k in entities and entities[k] and entities[k] not in search_keywords:
                    search_keywords += f" {entities[k]}"

        if cause_extra and cause_extra not in search_keywords:
            search_keywords = f"{search_keywords} {cause_extra}".strip()

        # Build percent-encoded search URLs
        google_url, so_url = build_search_urls(search_keywords)

        return ExplanationCard(
            error_id=error_id,
            exception_class=exc_class,
            title_th=title_th,
            summary_th=summary_th,
            mental_model_th=mental_model_th,
            fix_suggestions_th=fix_suggestions_th,
            search_keywords=search_keywords,
            google_search_url=google_url,
            stackoverflow_search_url=so_url,
            primary_frame=norm_tb.primary_frame,
            is_fallback=is_fallback,
            docstring=docstring,
        )
