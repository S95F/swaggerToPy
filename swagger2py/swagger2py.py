#!/usr/bin/env python3
"""
swagger2py — Swagger 2.0 / OpenAPI 3.0 / 3.1 → Python client SDK generator

CLI:
    python swagger2py.py spec.json -o client.py
    python swagger2py.py spec.yaml --async -o async_client.py
    python swagger2py.py spec.json --info

Programmatic:
    from swagger2py import generate
    code = generate(spec_dict)
    code = generate(spec_dict, use_async=True, validate=False)

Supported input formats:
    Swagger 2.0          swagger: "2.0"
    OpenAPI 3.0.x        openapi: "3.0.x"
    OpenAPI 3.1.x        openapi: "3.1.x"   (webhooks, JSON Schema aligned)
    AsyncAPI 2.x / 3.x   asyncapi: "2.x"    (event-driven channel stubs)

Modern API spec landscape:
    OpenAPI 3.1  - Current standard. Fully JSON Schema aligned. Replaces Swagger.
    AsyncAPI     - Event-driven / WebSocket / Kafka / MQTT / AMQP / SSE APIs.
    GraphQL SDL  - Type-based query APIs  (not converted — different paradigm).
    gRPC proto   - Binary RPC over HTTP/2 (not converted — different paradigm).
    RAML 1.0     - RESTful API Modeling Language (largely superseded by OAS).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ═══════════════════════════════════════════════════════════════════
# 1.  Spec loading & version detection
# ═══════════════════════════════════════════════════════════════════

def load_spec(path: str) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            sys.exit("PyYAML required for YAML input:  pip install pyyaml")
        return _yaml.safe_load(text)
    return json.loads(text)


def detect_version(spec: dict) -> str:
    if "swagger" in spec:
        return "swagger2"
    oa = spec.get("openapi", "")
    if oa.startswith("3.0"):
        return "oas30"
    if oa.startswith("3.1"):
        return "oas31"
    if "asyncapi" in spec:
        return "asyncapi"
    raise ValueError(
        "Unrecognised spec format — no 'swagger', 'openapi', or 'asyncapi' key found."
    )


# ═══════════════════════════════════════════════════════════════════
# 2.  $ref resolver (local JSON Pointer only)
# ═══════════════════════════════════════════════════════════════════

class RefResolver:
    def __init__(self, spec: dict) -> None:
        self._spec = spec
        self._cache: dict[str, Any] = {}

    def resolve(self, ref: str) -> dict:
        if ref in self._cache:
            return self._cache[ref]
        if not ref.startswith("#/"):
            raise ValueError(f"External $ref not supported: {ref!r}")
        node: Any = self._spec
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        self._cache[ref] = node
        return node

    def deref(self, obj: Any, _depth: int = 0) -> Any:
        """Follow $ref chains up to depth 40 (guards against cycles)."""
        if _depth > 40:
            return obj
        if isinstance(obj, dict) and "$ref" in obj:
            return self.deref(self.resolve(obj["$ref"]), _depth + 1)
        return obj


# ═══════════════════════════════════════════════════════════════════
# 3.  Swagger 2.0 → OAS3-like normaliser
# ═══════════════════════════════════════════════════════════════════

def _normalise_swagger2(spec: dict) -> dict:
    """Convert Swagger 2.0 to an OAS 3.0-compatible structure."""
    host = spec.get("host", "localhost")
    base = spec.get("basePath", "/")
    schemes = spec.get("schemes", ["https"])
    spec.setdefault("servers", [{"url": f"{schemes[0]}://{host}{base}"}])

    spec.setdefault("components", {})
    if "definitions" in spec:
        spec["components"].setdefault("schemas", spec.pop("definitions"))
    if "responses" in spec:
        spec["components"].setdefault("responses", spec.pop("responses"))
    if "parameters" in spec:
        spec["components"].setdefault("parameters", spec.pop("parameters"))

    if "securityDefinitions" in spec:
        sdefs = spec.pop("securityDefinitions")
        normalised: dict = {}
        for name, sd in sdefs.items():
            t = sd.get("type", "")
            if t == "basic":
                normalised[name] = {"type": "http", "scheme": "basic"}
            elif t == "apiKey":
                normalised[name] = {"type": "apiKey", "in": sd.get("in", "header"), "name": sd.get("name", name)}
            elif t == "oauth2":
                flows: dict = {}
                flow = sd.get("flow", "implicit")
                flow_map = {
                    "implicit": "implicit",
                    "password": "password",
                    "application": "clientCredentials",
                    "accessCode": "authorizationCode",
                }
                oas_flow = flow_map.get(flow, flow)
                flow_obj: dict = {}
                if "authorizationUrl" in sd:
                    flow_obj["authorizationUrl"] = sd["authorizationUrl"]
                if "tokenUrl" in sd:
                    flow_obj["tokenUrl"] = sd["tokenUrl"]
                flow_obj["scopes"] = sd.get("scopes", {})
                flows[oas_flow] = flow_obj
                normalised[name] = {"type": "oauth2", "flows": flows}
            else:
                normalised[name] = sd
        spec["components"]["securitySchemes"] = normalised

    global_consumes = spec.get("consumes", ["application/json"])

    for path_str, path_item in spec.get("paths", {}).items():
        for method in list(path_item.keys()):
            if method in ("parameters", "summary", "description", "$ref", "servers", "x-"):
                continue
            op = path_item[method]
            if not isinstance(op, dict):
                continue

            consumes = op.get("consumes", global_consumes)

            body_params = [p for p in op.get("parameters", []) if p.get("in") == "body"]
            form_params  = [p for p in op.get("parameters", []) if p.get("in") == "formData"]
            op["parameters"] = [
                p for p in op.get("parameters", [])
                if p.get("in") not in ("body", "formData")
            ]

            if body_params:
                bp = body_params[0]
                content: dict = {}
                for ct in consumes:
                    content[ct] = {"schema": bp.get("schema", {})}
                op["requestBody"] = {
                    "required": bp.get("required", False),
                    "description": bp.get("description", ""),
                    "content": content,
                }

            elif form_params:
                props: dict = {}
                required_list: list[str] = []
                for fp in form_params:
                    fname = fp["name"]
                    fschema = fp.get("schema", {
                        "type": fp.get("type", "string"),
                        "format": fp.get("format", ""),
                        "enum": fp.get("enum"),
                    })
                    fschema = {k: v for k, v in fschema.items() if v is not None}
                    if fp.get("description"):
                        fschema["description"] = fp["description"]
                    props[fname] = fschema
                    if fp.get("required"):
                        required_list.append(fname)
                schema: dict = {"type": "object", "properties": props}
                if required_list:
                    schema["required"] = required_list
                ct = "multipart/form-data" if "multipart/form-data" in consumes else "application/x-www-form-urlencoded"
                op.setdefault("requestBody", {
                    "required": bool(required_list),
                    "content": {ct: {"schema": schema}},
                })

            # Swagger 2.0 inline schema on non-body params
            for p in op.get("parameters", []):
                if "schema" not in p and "type" in p:
                    p["schema"] = {
                        k: p.pop(k)
                        for k in ("type", "format", "enum", "minimum", "maximum",
                                  "minLength", "maxLength", "pattern", "items",
                                  "default", "example")
                        if k in p
                    }

    return spec


# ═══════════════════════════════════════════════════════════════════
# 4.  Schema flattening: allOf / anyOf / oneOf / not
# ═══════════════════════════════════════════════════════════════════

def flatten_schema(schema: dict, resolver: RefResolver, _depth: int = 0) -> dict:
    """Dereference and flatten composition keywords into a single schema dict."""
    if _depth > 20:
        return schema
    schema = resolver.deref(schema)
    if not isinstance(schema, dict):
        return {}

    if "allOf" in schema:
        merged: dict = {}
        for sub in schema["allOf"]:
            sub = flatten_schema(sub, resolver, _depth + 1)
            _deep_merge(merged, sub)
        for k, v in schema.items():
            if k != "allOf":
                merged.setdefault(k, v)
        return merged

    # anyOf / oneOf — use first non-null concrete variant
    for kw in ("anyOf", "oneOf"):
        if kw in schema:
            variants = schema[kw]
            for v in variants:
                flat = flatten_schema(v, resolver, _depth + 1)
                t = flat.get("type")
                if isinstance(t, list):
                    non_null = [x for x in t if x != "null"]
                    if non_null:
                        flat["type"] = non_null[0]
                        flat["nullable"] = True
                        return flat
                elif t != "null":
                    return flat
            return schema

    return schema


def _deep_merge(target: dict, source: dict) -> None:
    for k, v in source.items():
        if k == "required" and isinstance(v, list) and isinstance(target.get(k), list):
            target[k] = list(dict.fromkeys(target[k] + v))
        elif k == "properties" and isinstance(v, dict) and isinstance(target.get(k), dict):
            for pk, pv in v.items():
                target[k].setdefault(pk, pv)
        else:
            target.setdefault(k, v)


# ═══════════════════════════════════════════════════════════════════
# 5.  Type annotation helpers
# ═══════════════════════════════════════════════════════════════════

_OAS_TO_PY: dict[str, str] = {
    "string":  "str",
    "integer": "int",
    "number":  "float",
    "boolean": "bool",
    "array":   "list",
    "object":  "dict",
    "null":    "None",
}


def schema_to_annotation(schema: dict, resolver: RefResolver) -> str:
    if not schema:
        return "Any"
    schema = flatten_schema(schema, resolver)

    t = schema.get("type")
    nullable = schema.get("nullable", False)

    # OAS 3.1: type may be a list, e.g. ["string", "null"]
    if isinstance(t, list):
        nullable = "null" in t
        non_null = [x for x in t if x != "null"]
        t = non_null[0] if non_null else None

    if t == "array":
        items = schema.get("items", {})
        inner = schema_to_annotation(items, resolver) if items else "Any"
        base = f"List[{inner}]"
    elif t == "object":
        if "additionalProperties" in schema:
            ap = schema["additionalProperties"]
            if isinstance(ap, bool):
                base = "Dict[str, Any]"
            else:
                vt = schema_to_annotation(ap, resolver)
                base = f"Dict[str, {vt}]"
        else:
            base = "Dict[str, Any]"
    elif t in _OAS_TO_PY:
        base = _OAS_TO_PY[t]
    elif t is None and ("properties" in schema or "additionalProperties" in schema):
        base = "Dict[str, Any]"
    else:
        base = "Any"

    return f"Optional[{base}]" if nullable else base


# ═══════════════════════════════════════════════════════════════════
# 6.  Validation code generation
# ═══════════════════════════════════════════════════════════════════

_FORMAT_PATTERNS: dict[str, str] = {
    "uuid":      r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    "date":      r"^\d{4}-\d{2}-\d{2}$",
    "date-time": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$",
    "time":      r"^\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$",
    "email":     r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    "uri":       r"^[a-zA-Z][a-zA-Z0-9+\-.]*:",
    "url":       r"^https?://",
    "ipv4":      r"^(\d{1,3}\.){3}\d{1,3}$",
    "ipv6":      r"^[0-9a-fA-F:]{2,39}$",
    "hostname":  r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$",
    "byte":      r"^[A-Za-z0-9+/]+=*$",
}


def _validation_checks(var: str, schema: dict) -> list[str]:
    checks: list[str] = []
    t = schema.get("type", "")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "")

    py_type_map = {
        "string":  "str",
        "integer": "int",
        "boolean": "bool",
        "array":   "list",
        "object":  "dict",
    }
    if t in py_type_map:
        checks.append(f"isinstance({var}, {py_type_map[t]})")
    elif t == "number":
        checks.append(f"isinstance({var}, (int, float))")

    fmt = schema.get("format", "")
    if fmt in _FORMAT_PATTERNS:
        pat = _FORMAT_PATTERNS[fmt]
        checks.append(f"re.match({pat!r}, str({var})) is not None")

    if "pattern" in schema:
        checks.append(f"re.match({schema['pattern']!r}, str({var})) is not None")

    if "enum" in schema:
        checks.append(f"{var} in {schema['enum']!r}")

    # Numeric constraints — OAS 3.0 style (boolean exclusiveMinimum)
    if "minimum" in schema:
        op = ">" if schema.get("exclusiveMinimum") is True else ">="
        checks.append(f"{var} {op} {schema['minimum']}")
    if "maximum" in schema:
        op = "<" if schema.get("exclusiveMaximum") is True else "<="
        checks.append(f"{var} {op} {schema['maximum']}")

    # OAS 3.1 style (numeric exclusiveMinimum / exclusiveMaximum)
    if isinstance(schema.get("exclusiveMinimum"), (int, float)):
        checks.append(f"{var} > {schema['exclusiveMinimum']}")
    if isinstance(schema.get("exclusiveMaximum"), (int, float)):
        checks.append(f"{var} < {schema['exclusiveMaximum']}")

    if "multipleOf" in schema:
        checks.append(f"{var} % {schema['multipleOf']} == 0")

    if "minLength" in schema:
        checks.append(f"len(str({var})) >= {schema['minLength']}")
    if "maxLength" in schema:
        checks.append(f"len(str({var})) <= {schema['maxLength']}")

    if "minItems" in schema:
        checks.append(f"len({var}) >= {schema['minItems']}")
    if "maxItems" in schema:
        checks.append(f"len({var}) <= {schema['maxItems']}")
    if schema.get("uniqueItems"):
        checks.append(f"len(set(map(str, {var}))) == len({var})")

    return checks


def gen_param_validation(var: str, schema: dict, required: bool, pad: str = "        ") -> list[str]:
    checks = _validation_checks(var, schema)
    if not checks:
        return []
    cond = " and ".join(checks)
    if required:
        return [
            f"{pad}if not ({cond}):",
            f'{pad}    raise ValueError(f"Invalid value for \'{var}\': {{{var}!r}}")',
        ]
    return [
        f"{pad}if {var} is not None and not ({cond}):",
        f'{pad}    raise ValueError(f"Invalid value for \'{var}\': {{{var}!r}}")',
    ]


# ═══════════════════════════════════════════════════════════════════
# 7.  Name helpers
# ═══════════════════════════════════════════════════════════════════

def _safe_name(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    if s and s[0].isdigit():
        s = "_" + s
    return s or "_"


def _class_name(title: str) -> str:
    parts = re.split(r"[\s\-_/\.]+", title.strip())
    return "".join(p.capitalize() for p in parts if p) or "ApiClient"


_PYTHON_KEYWORDS = frozenset({
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield", "type", "id", "filter", "input", "list",
    "dict", "set", "object", "format", "max", "min", "map", "zip",
})


def _param_name(raw: str) -> str:
    name = _safe_name(raw)
    if name in _PYTHON_KEYWORDS:
        name = name + "_"
    return name


def _unique_op_id(method: str, path: str, used: list[str]) -> str:
    parts = [method.lower()] + [
        re.sub(r"[{}]", "", seg) for seg in path.strip("/").split("/") if seg
    ]
    base = "_".join(_safe_name(p) for p in parts)
    name = base
    i = 2
    while name in used:
        name = f"{base}_{i}"
        i += 1
    used.append(name)
    return name


# ═══════════════════════════════════════════════════════════════════
# 8.  Parameter collection
# ═══════════════════════════════════════════════════════════════════

def collect_parameters(op: dict, path_item: dict, resolver: RefResolver) -> list[dict]:
    """Merge path-level + operation-level params; operation overrides by (name, in)."""
    merged: dict[tuple[str, str], dict] = {}
    for p in path_item.get("parameters", []):
        p = resolver.deref(p)
        merged[(p.get("name", ""), p.get("in", ""))] = p
    for p in op.get("parameters", []):
        p = resolver.deref(p)
        merged[(p.get("name", ""), p.get("in", ""))] = p
    return list(merged.values())


# ═══════════════════════════════════════════════════════════════════
# 9.  Request body → flat param list
# ═══════════════════════════════════════════════════════════════════

def extract_body_params(rb: dict, resolver: RefResolver) -> tuple[str, list[dict]]:
    """
    Returns (content_type, [param_dicts]) from a requestBody object.
    For application/json with an object schema, expands properties.
    For a non-object schema (e.g. raw array), returns a single 'body' param.
    """
    content = rb.get("content", {})
    rb_required = rb.get("required", False)

    for ct in (
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "application/octet-stream",
        "text/plain",
    ):
        if ct not in content:
            continue
        schema = content[ct].get("schema", {})
        schema = flatten_schema(schema, resolver)
        params: list[dict] = []

        if schema.get("type") == "object" or "properties" in schema:
            req_props = schema.get("required", [])
            for pname, pschema in schema.get("properties", {}).items():
                pschema = flatten_schema(pschema, resolver)
                params.append({
                    "name": pname,
                    "in": "body",
                    "schema": pschema,
                    "required": (pname in req_props) or rb_required,
                    "description": pschema.get("description", ""),
                })
        elif schema:
            params.append({
                "name": "body",
                "in": "body",
                "schema": schema,
                "required": rb_required,
                "description": rb.get("description", ""),
            })

        return ct, params

    return "application/json", []


# ═══════════════════════════════════════════════════════════════════
# 10. Return-type inference from responses
# ═══════════════════════════════════════════════════════════════════

def infer_return_type(responses: dict, resolver: RefResolver) -> str:
    for status in sorted(responses.keys(), key=lambda s: (s != "200", s)):
        try:
            sc = int(status)
        except (ValueError, TypeError):
            continue
        if not (200 <= sc < 300):
            continue
        resp = resolver.deref(responses[status])
        for ct, ct_val in resp.get("content", {}).items():
            if "json" in ct:
                s = ct_val.get("schema", {})
                if s:
                    return schema_to_annotation(flatten_schema(s, resolver), resolver)
        # response with no content (e.g. 204)
    return "Any"


# ═══════════════════════════════════════════════════════════════════
# 11. __init__ code generation
# ═══════════════════════════════════════════════════════════════════

def _emit_init(lines: list[str], server_urls: list[str], sec_schemes: dict) -> None:
    lines += [
        "    def __init__(",
        "        self,",
        "        base_url: Optional[str] = None,",
        "        security_config: Optional[Dict[str, Any]] = None,",
    ]
    if len(server_urls) > 1:
        lines.append("        server_index: int = 0,")
    lines += [
        "    ) -> None:",
        '        """',
        "        Args:",
        "            base_url: Override the default server URL.",
        "            security_config: Auth credentials keyed by scheme name.",
    ]

    if sec_schemes:
        for name, scheme in sec_schemes.items():
            st = scheme.get("type", "")
            sch = scheme.get("scheme", "")
            if st == "http" and sch == "basic":
                lines.append(f'                {name!r}: {{"username": "...", "password": "..."}}')
            elif st == "http" and sch == "bearer":
                lines.append(f'                {name!r}: {{"token": "..."}}')
            elif st == "apiKey":
                lines.append(f'                {name!r}: {{"api_key": "..."}}')
            elif st in ("oauth2", "openIdConnect"):
                lines.append(f'                {name!r}: {{"access_token": "..."}}')
            elif st == "mutualTLS":
                lines.append(f'                {name!r}: {{"cert": "/path/to/cert.pem"}}')

    if len(server_urls) > 1:
        lines.append(f"            server_index: Which server URL to use (0 = {server_urls[0]!r}).")

    lines += ['        """']

    if len(server_urls) > 1:
        lines += [
            f"        _servers: List[str] = {server_urls!r}",
            "        self.base_url: str = base_url or _servers[server_index]",
        ]
    else:
        lines.append(f"        self.base_url: str = base_url or {server_urls[0]!r}")

    lines += [
        "        self.security_config: Dict[str, Any] = security_config or {}",
        f"        self._sec_schemes: Dict[str, Any] = {sec_schemes!r}",
        "",
    ]

    # _apply_security helper
    lines += [
        "    def _apply_security(self, kw: Dict[str, Any], op_security: Optional[list] = None) -> Dict[str, Any]:",
        '        """Inject auth into request kwargs based on security_config."""',
        "        scheme_names: list = []",
        "        if op_security is not None:",
        "            for req in op_security:",
        "                if isinstance(req, dict):",
        "                    scheme_names.extend(req.keys())",
        "                elif isinstance(req, str):",
        "                    scheme_names.append(req)",
        "        else:",
        "            scheme_names = list(self.security_config.keys())",
        "        for name in scheme_names:",
        "            cfg = self.security_config.get(name)",
        "            if not cfg:",
        "                continue",
        "            sc = self._sec_schemes.get(name, {})",
        "            st = sc.get('type', '')",
        "            if st == 'http':",
        "                if sc.get('scheme') == 'basic':",
        "                    kw['auth'] = (cfg['username'], cfg['password'])",
        "                elif sc.get('scheme') == 'bearer':",
        "                    kw.setdefault('headers', {})['Authorization'] = f\"Bearer {cfg['token']}\"",
        "                else:",
        "                    kw.setdefault('headers', {})['Authorization'] = cfg.get('token', '')",
        "            elif st == 'apiKey':",
        "                loc = sc.get('in', 'header')",
        "                key_name = sc.get('name', name)",
        "                val = cfg.get('api_key', cfg.get('value', ''))",
        "                if loc == 'header':",
        "                    kw.setdefault('headers', {})[key_name] = val",
        "                elif loc == 'query':",
        "                    kw.setdefault('params', {})[key_name] = val",
        "                elif loc == 'cookie':",
        "                    kw.setdefault('cookies', {})[key_name] = val",
        "            elif st in ('oauth2', 'openIdConnect'):",
        "                token = cfg.get('access_token', cfg.get('token', ''))",
        "                kw.setdefault('headers', {})['Authorization'] = f'Bearer {token}'",
        "            elif st == 'mutualTLS':",
        "                kw['cert'] = cfg.get('cert')",
        "        return kw",
        "",
    ]


# ═══════════════════════════════════════════════════════════════════
# 12. Per-method code generation
# ═══════════════════════════════════════════════════════════════════

def _emit_method(
    lines: list[str],
    op: dict,
    resolver: RefResolver,
    use_async: bool,
    validate: bool,
) -> None:
    oid = op["oid"]
    method = op["method"]
    path = op["path"]
    all_raw_params: list[dict] = op["params"]
    rb = op.get("requestBody")
    security = op.get("security")
    deprecated = op.get("deprecated", False)

    # Split by location
    path_params   = [p for p in all_raw_params if p.get("in") == "path"]
    query_params  = [p for p in all_raw_params if p.get("in") == "query"]
    header_params = [p for p in all_raw_params if p.get("in") == "header"]
    cookie_params = [p for p in all_raw_params if p.get("in") == "cookie"]

    body_ct = "application/json"
    body_params: list[dict] = []
    if rb:
        rb = resolver.deref(rb)
        body_ct, body_params = extract_body_params(rb, resolver)

    # Ordered: required first, optional second; within each group: path, query, header, cookie, body
    def _is_required(p: dict) -> bool:
        return bool(p.get("required", p.get("in") == "path"))

    ordered = (
        [p for p in path_params if _is_required(p)]
        + [p for p in query_params if _is_required(p)]
        + [p for p in header_params if _is_required(p)]
        + [p for p in cookie_params if _is_required(p)]
        + [p for p in body_params if _is_required(p)]
        + [p for p in path_params if not _is_required(p)]
        + [p for p in query_params if not _is_required(p)]
        + [p for p in header_params if not _is_required(p)]
        + [p for p in cookie_params if not _is_required(p)]
        + [p for p in body_params if not _is_required(p)]
    )

    # Return type
    ret_ann = infer_return_type(op.get("responses", {}), resolver)

    # Function signature
    sig_parts = ["self"]
    for p in ordered:
        pname = _param_name(p["name"])
        schema = flatten_schema(p.get("schema", {}), resolver)
        ann = schema_to_annotation(schema, resolver)
        req = _is_required(p)
        if req:
            sig_parts.append(f"{pname}: {ann}")
        else:
            if "Optional" in ann:
                sig_parts.append(f"{pname}: {ann} = None")
            else:
                sig_parts.append(f"{pname}: Optional[{ann}] = None")

    kw = "async def" if use_async else "def"
    lines += ["", f"    {kw} {oid}({', '.join(sig_parts)}) -> {ret_ann}:"]

    # Docstring
    summary = (op.get("summary") or "").strip()
    description = (op.get("description") or "").strip()
    tags = op.get("tags", [])
    doc: list[str] = ['        """']
    if deprecated:
        doc.append("        .. deprecated::")
    if summary:
        doc.append(f"        {summary}")
    if description and description != summary:
        doc += ["        ", f"        {description}"]
    doc.append(f"        ``{method.upper()} {path}``")
    if tags:
        doc.append(f"        Tags: {', '.join(tags)}")
    if ordered:
        doc.append("        ")
        doc.append("        Args:")
        for p in ordered:
            pname = _param_name(p["name"])
            loc = p.get("in", "")
            req_str = "required" if _is_required(p) else "optional"
            pdesc = (p.get("description") or "").strip()
            schema = flatten_schema(p.get("schema", {}), resolver)
            ann = schema_to_annotation(schema, resolver)
            extra = ""
            if schema.get("enum"):
                extra = f" Allowed: {schema['enum']!r}."
            doc.append(f"            {pname} ({ann}, {loc}, {req_str}): {pdesc}{extra}".rstrip(": "))
    doc += ["        ", f"        Returns:", f"            {ret_ann}", '        """']
    lines.extend(doc)

    # ── URL ──────────────────────────────────────────────────────
    fmt_path = path
    for pp in path_params:
        pname = _param_name(pp["name"])
        fmt_path = fmt_path.replace("{" + pp["name"] + "}", "{" + pname + "}")
    lines.append(f'        _url = self.base_url + f"{fmt_path}"')

    # ── Validation ───────────────────────────────────────────────
    if validate:
        for p in ordered:
            pname = _param_name(p["name"])
            schema = flatten_schema(p.get("schema", {}), resolver)
            req = _is_required(p)
            lines.extend(gen_param_validation(pname, schema, req))

    # ── Build request kwargs ──────────────────────────────────────
    lines.append("        _kw: Dict[str, Any] = {}")

    def _emit_location(params: list[dict], kw_key: str, loc_label: str) -> None:
        if not params:
            return
        lines.append(f"        _{loc_label}: Dict[str, Any] = {{}}")
        for p in params:
            pname = _param_name(p["name"])
            raw = p["name"]
            if _is_required(p):
                lines.append(f"        _{loc_label}[{raw!r}] = {pname}")
            else:
                lines.append(f"        if {pname} is not None: _{loc_label}[{raw!r}] = {pname}")
        lines.append(f"        if _{loc_label}: _kw[{kw_key!r}] = _{loc_label}")

    _emit_location(query_params, "params", "params")
    _emit_location(header_params, "headers", "headers")
    _emit_location(cookie_params, "cookies", "cookies")

    # Body
    if body_params:
        if "json" in body_ct:
            lines.append("        _body: Dict[str, Any] = {}")
            for p in body_params:
                pname = _param_name(p["name"])
                raw = p["name"]
                if _is_required(p):
                    if raw == "body":
                        lines.append(f"        _body = {pname} if isinstance({pname}, dict) else {{'body': {pname}}}")
                    else:
                        lines.append(f"        _body[{raw!r}] = {pname}")
                else:
                    if raw == "body":
                        lines.append(f"        if {pname} is not None: _body = {pname} if isinstance({pname}, dict) else {{'body': {pname}}}")
                    else:
                        lines.append(f"        if {pname} is not None: _body[{raw!r}] = {pname}")
            lines.append("        if _body: _kw['json'] = _body")
        elif "form" in body_ct or "multipart" in body_ct:
            form_key = "files" if "multipart" in body_ct else "data"
            lines.append(f"        _form: Dict[str, Any] = {{}}")
            for p in body_params:
                pname = _param_name(p["name"])
                raw = p["name"]
                if _is_required(p):
                    lines.append(f"        _form[{raw!r}] = {pname}")
                else:
                    lines.append(f"        if {pname} is not None: _form[{raw!r}] = {pname}")
            lines.append(f"        if _form: _kw[{form_key!r}] = _form")
        else:
            # Raw/binary/text body
            lines += [
                "        if body is not None: _kw['data'] = body",
                f"        _kw.setdefault('headers', {{}})['Content-Type'] = {body_ct!r}",
            ]

    # Security
    if security is not None:
        lines.append(f"        _kw = self._apply_security(_kw, {security!r})")
    else:
        lines.append("        _kw = self._apply_security(_kw)")

    # HTTP call
    if use_async:
        lines += [
            "        async with httpx.AsyncClient() as _client:",
            f"            _resp = await _client.{method}(_url, **_kw)",
        ]
    else:
        lines.append(f"        _resp = requests.{method}(_url, **_kw)")

    # Response handling
    lines += [
        "        _resp.raise_for_status()",
        "        _ct = _resp.headers.get('Content-Type', '')",
        "        if 'json' in _ct:",
        "            return _resp.json()",
        "        if _resp.content:",
        "            return _resp.text",
        "        return None",
    ]


# ═══════════════════════════════════════════════════════════════════
# 13. AsyncAPI stub generator
# ═══════════════════════════════════════════════════════════════════

def _generate_asyncapi(spec: dict) -> str:
    title = spec.get("info", {}).get("title", "AsyncApiClient")
    av = spec.get("asyncapi", "?")
    class_name = _class_name(title)
    channels = spec.get("channels", {})
    operations = spec.get("operations", {})

    lines = [
        "# Generated by swagger2py (AsyncAPI stub)",
        "# AsyncAPI describes event-driven APIs — this generates publish/subscribe stubs.",
        "# Implement the transport layer (WebSocket, Kafka, MQTT, etc.) in each method.",
        "from __future__ import annotations",
        "from typing import Any, Callable, Dict, Optional",
        "",
        "",
        f"class {class_name}:",
        f'    """',
        f"    AsyncAPI {av} — {title}",
        f'    """',
        "",
        "    def __init__(self) -> None:",
        "        self._handlers: Dict[str, Callable] = {}",
        "",
        "    def on(self, channel: str, handler: Callable) -> None:",
        '        """Register a message handler for a channel."""',
        "        self._handlers[channel] = handler",
        "",
        "    def dispatch(self, channel: str, message: Any) -> None:",
        '        """Dispatch a received message to the registered handler."""',
        "        if channel in self._handlers:",
        "            self._handlers[channel](message)",
        "",
    ]

    emitted: set[str] = set()

    # AsyncAPI 3.x uses top-level operations
    for op_id, op_obj in operations.items():
        if not isinstance(op_obj, dict):
            continue
        action = op_obj.get("action", "")
        ch_ref = op_obj.get("channel", {}).get("$ref", "")
        ch_name = ch_ref.split("/")[-1] if ch_ref else op_id
        safe = _safe_name(op_id)
        if action == "receive":
            lines += [
                f"    def {safe}(self, handler: Callable) -> None:",
                f'        """Subscribe: {ch_name}"""',
                f"        self.on({ch_name!r}, handler)",
                "",
            ]
        elif action == "send":
            lines += [
                f"    def {safe}(self, message: Any) -> None:",
                f'        """Publish: {ch_name}"""',
                f"        raise NotImplementedError('Implement send transport for {ch_name}')",
                "",
            ]
        emitted.add(ch_name)

    # AsyncAPI 2.x uses subscribe/publish inside channel
    for ch_name, ch_item in channels.items():
        if not isinstance(ch_item, dict):
            continue
        safe_ch = _safe_name(ch_name)
        if "subscribe" in ch_item and ch_name not in emitted:
            lines += [
                f"    def subscribe_{safe_ch}(self, handler: Callable) -> None:",
                f'        """Subscribe to channel: {ch_name}"""',
                f"        self.on({ch_name!r}, handler)",
                "",
            ]
        if "publish" in ch_item:
            lines += [
                f"    def publish_{safe_ch}(self, message: Any) -> None:",
                f'        """Publish to channel: {ch_name}"""',
                f"        raise NotImplementedError('Implement publish transport for {ch_name}')",
                "",
            ]

    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════════
# 14. Main generate() entry point
# ═══════════════════════════════════════════════════════════════════

def generate(spec: dict, use_async: bool = False, validate: bool = True) -> str:
    """
    Convert a spec dict to a Python client SDK string.

    Args:
        spec:       Parsed Swagger 2.0 / OpenAPI 3.x / AsyncAPI dict.
        use_async:  Generate async methods with httpx instead of requests.
        validate:   Emit inline parameter validation in generated methods.

    Returns:
        Python source code as a string.
    """
    version = detect_version(spec)

    if version == "asyncapi":
        return _generate_asyncapi(spec)

    import copy
    spec = copy.deepcopy(spec)
    if version == "swagger2":
        spec = _normalise_swagger2(spec)

    resolver = RefResolver(spec)

    title = spec.get("info", {}).get("title", "ApiClient")
    class_name = _class_name(title)
    version_str = spec.get("info", {}).get("version", "")
    description = (spec.get("info", {}).get("description") or "").strip()
    spec_ver = spec.get("openapi") or spec.get("swagger", "?")

    servers = spec.get("servers", [{"url": "/"}])
    server_urls = [s["url"] for s in servers if isinstance(s, dict)]
    if not server_urls:
        server_urls = ["/"]

    sec_schemes: dict = spec.get("components", {}).get("securitySchemes", {})

    # ── Collect operations ────────────────────────────────────────
    operations: list[dict] = []
    used_names: list[str] = []

    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        path_item = resolver.deref(path_item)
        for method in ("get", "post", "put", "patch", "delete", "head", "options", "trace"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue

            raw_oid = op.get("operationId") or ""
            if raw_oid:
                oid = _safe_name(raw_oid)
                if oid in used_names:
                    oid = _unique_op_id(method, path, used_names)
                else:
                    used_names.append(oid)
            else:
                oid = _unique_op_id(method, path, used_names)

            params = collect_parameters(op, path_item, resolver)
            operations.append({
                "oid": oid,
                "method": method,
                "path": path,
                "params": params,
                "requestBody": op.get("requestBody"),
                "responses": op.get("responses", {}),
                "security": op.get("security"),
                "summary": op.get("summary", ""),
                "description": op.get("description", ""),
                "deprecated": op.get("deprecated", False),
                "tags": op.get("tags", []),
            })

    # ── Assemble source ───────────────────────────────────────────
    lines: list[str] = [
        "# Generated by swagger2py",
        f"# Spec:   {spec_ver}",
        f"# Title:  {title}" + (f" v{version_str}" if version_str else ""),
        "#",
        "# Supported input formats:",
        "#   Swagger 2.0 / OpenAPI 3.0 / OpenAPI 3.1 / AsyncAPI 2+3",
        "#",
        "# Modern formats that succeeded Swagger:",
        "#   OpenAPI 3.1  — current standard, fully JSON Schema aligned",
        "#   AsyncAPI     — event-driven APIs (WebSocket, Kafka, MQTT, AMQP, SSE)",
        "#   GraphQL SDL  — type-based query APIs",
        "#   gRPC proto   — binary RPC over HTTP/2",
        "from __future__ import annotations",
        "",
        "import re",
        "from typing import Any, Dict, List, Optional, Union",
    ]

    if use_async:
        lines += ["", "import httpx"]
    else:
        lines += ["", "import requests"]

    lines += ["", "", f"class {class_name}:"]

    # Class docstring
    doc = ['    """', f"    {title}" + (f" v{version_str}" if version_str else "")]
    if description:
        doc += ["    ", f"    {description}"]
    doc += ["    ", f"    Spec version: {spec_ver}", '    """', ""]
    lines.extend(doc)

    _emit_init(lines, server_urls, sec_schemes)

    for op in operations:
        _emit_method(lines, op, resolver, use_async, validate)

    # Webhooks (OAS 3.1)
    webhooks = spec.get("webhooks", {})
    if webhooks:
        lines += ["", "    # ── Webhooks (OAS 3.1) ─────────────────────────────────────────"]
        for wh_name, wh_item in webhooks.items():
            if not isinstance(wh_item, dict):
                continue
            for wh_method, wh_op in wh_item.items():
                if not isinstance(wh_op, dict) or wh_method in ("summary", "description", "parameters"):
                    continue
                oid = _safe_name(f"webhook_{wh_name}_{wh_method}")
                lines += [
                    "",
                    f"    def {oid}(self, payload: Any = None) -> Any:",
                    f'        """Webhook handler: {wh_name} ({wh_method.upper()})"""',
                    f"        raise NotImplementedError('Implement webhook handler: {wh_name}')",
                ]

    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════════
# 15. CLI
# ═══════════════════════════════════════════════════════════════════

def _spec_summary(spec: dict) -> None:
    version = detect_version(spec)
    info = spec.get("info", {})
    paths = spec.get("paths", {})
    ops = sum(
        1 for pi in paths.values() if isinstance(pi, dict)
        for m in ("get", "post", "put", "patch", "delete", "head", "options", "trace")
        if m in pi
    )
    schemas = len(spec.get("components", {}).get("schemas", {}))
    sec = list(spec.get("components", {}).get("securitySchemes", {}).keys())
    servers = [s.get("url", "") for s in spec.get("servers", [])]

    print(f"Format:   {version}")
    print(f"Title:    {info.get('title', '?')}")
    print(f"Version:  {info.get('version', '?')}")
    print(f"Paths:    {len(paths)}")
    print(f"Ops:      {ops}")
    print(f"Schemas:  {schemas}")
    print(f"Security: {sec or 'none'}")
    print(f"Servers:  {servers}")

    if version == "asyncapi":
        channels = spec.get("channels", {})
        print(f"Channels: {len(channels)}")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="swagger2py",
        description="Convert Swagger 2.0 / OpenAPI 3.x / AsyncAPI specs to a Python SDK.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python swagger2py.py pet.json -o pet_client.py
  python swagger2py.py openapi.yaml --async -o async_client.py
  python swagger2py.py spec.json --info
  python swagger2py.py spec.json --no-validate -o client.py
        """,
    )
    ap.add_argument("spec", help="Spec file path (.json / .yaml / .yml)")
    ap.add_argument("-o", "--output", help="Output .py file (default: <title>.py)")
    ap.add_argument(
        "--async", dest="use_async", action="store_true",
        help="Generate async client using httpx instead of requests",
    )
    ap.add_argument(
        "--no-validate", dest="validate", action="store_false",
        help="Omit inline parameter validation in the generated code",
    )
    ap.add_argument(
        "--info", action="store_true",
        help="Print spec summary and exit without generating code",
    )
    args = ap.parse_args()

    spec = load_spec(args.spec)

    if args.info:
        _spec_summary(spec)
        return

    code = generate(spec, use_async=args.use_async, validate=args.validate)

    if args.output:
        out = Path(args.output)
    else:
        t = spec.get("info", {}).get("title", "client")
        out = Path(_safe_name(t.replace(" ", "_")) + ".py")

    out.write_text(code, encoding="utf-8")
    print(f"Written: {out}  ({len(code):,} bytes, {len(code.splitlines())} lines)")


if __name__ == "__main__":
    main()
