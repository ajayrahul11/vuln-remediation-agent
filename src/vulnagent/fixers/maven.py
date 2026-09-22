"""Edit a pom.xml in place with regexes, so formatting and comments survive.

Cases, in order:
  1. a <dependency> for the package carries a literal <version>   -> replace it
  2. ... carries <version>${prop}</version>                       -> set <prop>
     (moves every dependency that shares the property, which is what you want
     for e.g. log4j-core + log4j-api)
  3. no version anywhere (managed by a parent/BOM, or transitive) -> pin it in
     <dependencyManagement>, which overrides the parent's managed version
"""

from __future__ import annotations

import re

_DEP = re.compile(r"<dependency>.*?</dependency>", re.DOTALL)
_EXCL = re.compile(r"<exclusions>.*?</exclusions>", re.DOTALL)
_VERSION = re.compile(r"(<version>\s*)([^<]*?)(\s*</version>)")
_PROP_REF = re.compile(r"^\$\{([^}]+)\}$")


def _tag(block: str, name: str) -> str | None:
    m = re.search(rf"<{name}>\s*([^<]*?)\s*</{name}>", block)
    return m.group(1) if m else None


def _set_property(text: str, prop: str, value: str) -> str | None:
    pat = re.compile(rf"(<{re.escape(prop)}>\s*)[^<]*?(\s*</{re.escape(prop)}>)")
    if pat.search(text):
        return pat.sub(lambda m: f"{m.group(1)}{value}{m.group(2)}", text, count=1)
    if "</properties>" in text:
        return text.replace("</properties>", f"    <{prop}>{value}</{prop}>\n    </properties>", 1)
    return None


def _pin(text: str, group: str, artifact: str, fixed: str) -> str:
    dep = (
        "            <dependency>\n"
        f"                <groupId>{group}</groupId>\n"
        f"                <artifactId>{artifact}</artifactId>\n"
        f"                <version>{fixed}</version>\n"
        "            </dependency>\n"
    )
    if "</dependencyManagement>" in text:
        end = text.index("</dependencyManagement>")
        at = text.rfind("</dependencies>", 0, end)
        return text[:at] + dep.replace("            ", "        ", 1) + "        " + text[at:]
    block = (
        "    <dependencyManagement>\n        <dependencies>\n"
        + dep
        + "        </dependencies>\n    </dependencyManagement>\n\n"
    )
    at = text.rindex("</project>")
    return text[:at] + block + text[at:]


def bump_pom(text: str, package: str, fixed: str) -> tuple[str, str]:
    """Returns (new_text, human description). Raises ValueError if nothing changed."""
    group, artifact = package.split(":", 1)
    new = text
    how = ""

    for m in _DEP.finditer(text):
        block = m.group(0)
        bare = _EXCL.sub("", block)  # an <exclusion> naming this artifact is not a match
        if _tag(bare, "groupId") != group or _tag(bare, "artifactId") != artifact:
            continue
        version = _tag(bare, "version")
        if version is None:
            continue
        ref = _PROP_REF.match(version)
        if ref:
            out = _set_property(new, ref.group(1), fixed)
            if out is None:
                continue
            new, how = out, f"set property {ref.group(1)} = {fixed}"
        else:
            new_block = _VERSION.sub(lambda v: f"{v.group(1)}{fixed}{v.group(3)}", block, count=1)
            new, how = new.replace(block, new_block, 1), f"set {package} version to {fixed}"
        break

    if new == text:
        new, how = _pin(text, group, artifact, fixed), f"pin {package} to {fixed} in dependencyManagement"
    if new == text:
        raise ValueError(f"pom.xml unchanged after bumping {package}")
    return new, how
