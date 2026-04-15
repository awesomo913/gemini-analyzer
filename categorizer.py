"""Conversation categorization engine with coding project detection."""

import re
from dataclasses import dataclass
from typing import Optional
import logging

from parser import Conversation

logger = logging.getLogger(__name__)

CODING_KEYWORDS = {
    "python", "javascript", "typescript", "java", "c++", "c#", "rust", "go",
    "html", "css", "react", "vue", "angular", "node", "django", "flask",
    "fastapi", "express", "sql", "database", "api", "endpoint", "function",
    "class", "variable", "loop", "array", "list", "dictionary", "dict",
    "import", "export", "module", "package", "library", "framework",
    "debug", "error", "exception", "traceback", "stacktrace", "bug",
    "git", "github", "commit", "branch", "merge", "pull request",
    "docker", "kubernetes", "aws", "azure", "gcp", "deploy", "ci/cd",
    "algorithm", "data structure", "regex", "async", "await", "thread",
    "socket", "http", "rest", "graphql", "websocket", "oauth",
    "tkinter", "pyqt", "kivy", "electron", "flutter", "swift", "kotlin",
    "tensorflow", "pytorch", "pandas", "numpy", "matplotlib",
    "pip install", "npm install", "cargo", "gradle", "maven", "cmake",
    "def ", "class ", "import ", "from ", "return ", "if __name__",
    "console.log", "print(", "System.out", "fmt.Println",
    "dockerfile", "yaml", "json", "xml", "csv", "toml",
    "unittest", "pytest", "jest", "mocha", "selenium",
    "raspberry pi", "arduino", "gpio", "serial", "uart",
    "app", "application", "program", "script", "bot", "tool", "utility",
    "gui", "interface", "window", "button", "widget", "layout",
    "build", "compile", "run", "execute", "install", "setup",
    "code", "coding", "programming", "developer", "software",
}

APP_CREATION_PATTERNS = [
    r"(?:create|build|make|develop|write|design|code)\s+(?:a|an|the|my)?\s*(?:\w+\s+)?(?:app|application|program|tool|bot|script|game|website|site|dashboard|gui|interface|plugin|extension|addon|mod|utility)",
    r"(?:i\s+(?:want|need|am\s+(?:trying|making|building|creating|working\s+on)))\s+(?:a|an|the|my)?\s*(?:\w+\s+)?(?:app|application|program|tool|bot|script|game|website|site|dashboard|gui)",
    r"(?:help\s+me\s+(?:build|create|make|code|develop|write))\s+(?:a|an|the|my)?\s*(?:\w+\s+)?(?:app|application|program|tool|bot|script|game|website|site)",
    r"(?:name|call|title)\s+(?:it|this|the\s+app|the\s+program|the\s+project)\s+['\"]?(\w[\w\s]{1,40})['\"]?",
    r"(?:let'?s?\s+call\s+it|the\s+name\s+(?:is|should\s+be|will\s+be))\s+['\"]?(\w[\w\s]{1,40})['\"]?",
]

PROJECT_NAME_PATTERNS = [
    r"(?:called?|named?|titled?)\s+['\"]([A-Z][\w\s]{1,30})['\"]",
    r"['\"]([A-Z][\w]{2,25}(?:\s[A-Z][\w]+)*)['\"]",
    r"(?:project|app|program|tool|game)\s*(?:name|:)\s*['\"]?([A-Z][\w\s]{2,30})['\"]?",
]

CATEGORIES = {
    "Coding & Programming": {
        "keywords": CODING_KEYWORDS,
        "subcategories": {
            "App/Program Creation": [
                "create app", "build app", "make app", "develop app",
                "create program", "build program", "make program",
                "application development", "gui app", "desktop app",
                "web app", "mobile app", "game development",
            ],
            "Web Development": [
                "html", "css", "javascript", "react", "vue", "angular",
                "website", "web page", "frontend", "backend", "fullstack",
                "node.js", "express", "django", "flask", "fastapi",
                "responsive", "bootstrap", "tailwind",
            ],
            "Data Science & ML": [
                "pandas", "numpy", "matplotlib", "tensorflow", "pytorch",
                "machine learning", "deep learning", "neural network",
                "data analysis", "dataset", "model training", "ai model",
                "scikit", "jupyter", "notebook",
            ],
            "Scripting & Automation": [
                "automate", "script", "batch", "cron", "scheduled",
                "web scraping", "selenium", "beautifulsoup", "bot",
                "automation", "workflow",
            ],
            "Debugging & Troubleshooting": [
                "error", "bug", "fix", "debug", "traceback", "exception",
                "not working", "fails", "crash", "broken", "issue",
            ],
            "DevOps & Deployment": [
                "docker", "kubernetes", "deploy", "ci/cd", "github actions",
                "aws", "azure", "gcp", "heroku", "server", "hosting",
                "nginx", "apache",
            ],
            "API & Integration": [
                "api", "rest", "graphql", "webhook", "endpoint",
                "authentication", "oauth", "jwt", "token",
            ],
            "Database": [
                "sql", "database", "postgresql", "mysql", "sqlite",
                "mongodb", "redis", "query", "table", "schema",
            ],
            "General Coding Help": [],
        },
    },
    "Creative Writing": {
        "keywords": {
            "story", "poem", "poetry", "novel", "character", "plot",
            "narrative", "fiction", "creative writing", "dialogue",
            "screenplay", "lyrics", "song", "verse", "prose",
            "fantasy", "sci-fi", "romance", "mystery", "thriller",
            "chapter", "scene", "setting", "protagonist", "antagonist",
        },
        "subcategories": {
            "Fiction & Stories": ["story", "novel", "fiction", "chapter", "tale"],
            "Poetry": ["poem", "poetry", "verse", "rhyme", "haiku", "sonnet"],
            "Content Creation": ["blog", "article", "post", "content", "copywriting"],
            "Screenwriting": ["screenplay", "script", "dialogue", "scene"],
        },
    },
    "Research & Learning": {
        "keywords": {
            "explain", "what is", "how does", "why does", "history of",
            "definition", "meaning", "difference between", "compare",
            "tutorial", "learn", "understand", "concept", "theory",
            "study", "research", "analysis", "review",
            "pros and cons", "advantages", "disadvantages",
        },
        "subcategories": {
            "Science & Tech": ["science", "physics", "chemistry", "biology", "technology"],
            "History & Culture": ["history", "culture", "civilization", "ancient", "war"],
            "Education": ["learn", "study", "tutorial", "course", "teach", "explain"],
            "General Knowledge": [],
        },
    },
    "Business & Professional": {
        "keywords": {
            "email", "resume", "cover letter", "business plan",
            "marketing", "strategy", "proposal", "presentation",
            "meeting", "interview", "negotiate", "salary",
            "startup", "entrepreneur", "revenue", "profit",
            "client", "customer", "brand", "linkedin",
        },
        "subcategories": {
            "Communication": ["email", "letter", "message", "memo", "announce"],
            "Career": ["resume", "cover letter", "interview", "job", "career"],
            "Marketing": ["marketing", "seo", "advertising", "brand", "campaign"],
            "Planning": ["business plan", "strategy", "proposal", "roadmap"],
        },
    },
    "Math & Science": {
        "keywords": {
            "calculate", "equation", "formula", "math", "algebra",
            "calculus", "statistics", "probability", "geometry",
            "physics", "chemistry", "biology", "scientific",
            "graph", "plot", "solve", "proof", "theorem",
        },
        "subcategories": {
            "Mathematics": ["math", "algebra", "calculus", "geometry", "equation"],
            "Statistics": ["statistics", "probability", "distribution", "mean", "median"],
            "Physics": ["physics", "force", "energy", "velocity", "quantum"],
            "Other Sciences": [],
        },
    },
    "Naming & Branding": {
        "keywords": {
            "name for", "suggest a name", "app name", "project name",
            "brand name", "company name", "product name", "title",
            "catchy name", "cool name", "unique name", "creative name",
            "logo", "branding", "tagline", "slogan", "motto",
        },
        "subcategories": {
            "App/Project Names": ["app name", "project name", "program name", "tool name"],
            "Business Names": ["company name", "brand name", "business name", "startup name"],
            "Other Naming": [],
        },
    },
    "Personal & Lifestyle": {
        "keywords": {
            "recipe", "cooking", "health", "fitness", "travel",
            "hobby", "relationship", "advice", "recommend",
            "workout", "diet", "meditation", "sleep",
            "movie", "book", "music", "game", "entertainment",
        },
        "subcategories": {
            "Health & Fitness": ["health", "fitness", "workout", "diet", "exercise"],
            "Recommendations": ["recommend", "suggest", "best", "top", "favorite"],
            "Lifestyle": ["recipe", "travel", "hobby", "home", "garden"],
        },
    },
}


@dataclass
class CategoryResult:
    category: str
    subcategory: str
    confidence: float
    tags: list[str]
    is_coding: bool
    is_app_creation: bool
    project_name: str


def _text_score(text_lower: str, keywords: set) -> int:
    """Score text against keywords. Expects pre-lowercased text."""
    score = 0
    for kw in keywords:
        if kw in text_lower:
            score += 1
    return score


def _detect_app_creation(text_lower: str) -> bool:
    """Detect app creation patterns. Expects pre-lowercased text."""
    for pattern in APP_CREATION_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def _detect_project_name(text: str) -> str:
    for pattern in PROJECT_NAME_PATTERNS:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            if 2 < len(name) < 35:
                return name

    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if re.match(r'^#\s+([A-Z][\w\s]{2,30})$', line):
            return re.match(r'^#\s+([A-Z][\w\s]{2,30})$', line).group(1).strip()

    return ""


def categorize_conversation(conv: Conversation) -> CategoryResult:
    full_text = conv.full_text
    user_text = " ".join(m.text for m in conv.user_messages)
    has_code_blocks = conv.has_code

    # Truncate for scoring — first 2000 chars is enough for categorization
    # This prevents scanning massive code blocks for keywords
    scoring_text = full_text[:2000].lower()
    user_text_lower = user_text[:1000].lower()

    scores: dict[str, int] = {}
    best_sub: dict[str, tuple[str, int]] = {}

    for cat_name, cat_data in CATEGORIES.items():
        kw_set = cat_data["keywords"]
        if not isinstance(kw_set, set):
            kw_set = set(kw_set)
        score = _text_score(scoring_text, kw_set)

        if cat_name == "Coding & Programming":
            if has_code_blocks:
                score += 50
            if "```" in full_text[:5000]:
                score += 30

        scores[cat_name] = score

        sub_scores = {}
        for sub_name, sub_keywords in cat_data.get("subcategories", {}).items():
            sub_score = _text_score(scoring_text, set(sub_keywords)) if sub_keywords else 0
            sub_scores[sub_name] = sub_score

        if sub_scores:
            best = max(sub_scores.items(), key=lambda x: x[1])
            best_sub[cat_name] = best

    if not scores or max(scores.values()) == 0:
        return CategoryResult(
            category="Uncategorized",
            subcategory="",
            confidence=0.0,
            tags=[],
            is_coding=False,
            is_app_creation=False,
            project_name="",
        )

    best_cat = max(scores.items(), key=lambda x: x[1])
    cat_name = best_cat[0]
    cat_score = best_cat[1]

    total = sum(scores.values()) or 1
    confidence = min(cat_score / total, 1.0)

    sub_name = ""
    if cat_name in best_sub:
        sub_info = best_sub[cat_name]
        sub_name = sub_info[0] if sub_info[1] > 0 else ""
        if cat_name == "Coding & Programming" and not sub_name:
            sub_name = "General Coding Help"

    is_coding = cat_name == "Coding & Programming"
    is_app_creation = is_coding and _detect_app_creation(user_text_lower)

    if is_app_creation and not sub_name:
        sub_name = "App/Program Creation"

    project_name = ""
    if is_coding:
        project_name = _detect_project_name(full_text[:3000])

    tags = []
    if is_coding:
        tags.append("coding")
        # Use pre-lowered text for fast language detection
        detect_text = scoring_text
        lang_keywords = {
            "python": ("python", ".py", "pip ", "import ", "def "),
            "javascript": ("javascript", ".js", "npm ", "const ", "let ", "=> "),
            "typescript": ("typescript", ".ts", "interface "),
            "java": (".java", "public class", "system.out"),
            "c++": ("c++", "cpp", "#include", "iostream"),
            "c#": ("c#", "csharp", ".cs", "using system"),
            "rust": ("rust", ".rs", "cargo"),
            "go": ("golang", ".go", "func ", "package main"),
            "html/css": ("html", "css", "<div", "font-size"),
            "react": ("react", "jsx", "tsx", "usestate"),
            "sql": ("select ", "insert ", "create table"),
            "shell": ("bash", "chmod", "sudo", "apt-get"),
        }
        for lang, kws in lang_keywords.items():
            if any(kw in detect_text for kw in kws):
                tags.append(lang)

    if has_code_blocks:
        tags.append("has-code")
    if is_app_creation:
        tags.append("app-creation")
    if project_name:
        tags.append(f"project:{project_name}")

    return CategoryResult(
        category=cat_name,
        subcategory=sub_name,
        confidence=confidence,
        tags=tags,
        is_coding=is_coding,
        is_app_creation=is_app_creation,
        project_name=project_name,
    )


def categorize_all(conversations: list[Conversation]) -> list[Conversation]:
    for conv in conversations:
        result = categorize_conversation(conv)
        conv.category = result.category
        conv.subcategory = result.subcategory
        conv.tags = result.tags
        conv.coding_project_name = result.project_name
    logger.info("Categorized %d conversations", len(conversations))
    return conversations
