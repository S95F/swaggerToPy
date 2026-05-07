package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// ---------- generic helpers ----------

func asMap(v interface{}) map[string]interface{} {
	if m, ok := v.(map[string]interface{}); ok {
		return m
	}
	return nil
}

func asSlice(v interface{}) []interface{} {
	if s, ok := v.([]interface{}); ok {
		return s
	}
	return nil
}

func asString(v interface{}) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func asBool(v interface{}) bool {
	if b, ok := v.(bool); ok {
		return b
	}
	return false
}

func hasKey(m map[string]interface{}, k string) bool {
	if m == nil {
		return false
	}
	_, ok := m[k]
	return ok
}

func sortedKeys(m map[string]interface{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func containsStr(list []string, v string) bool {
	for _, s := range list {
		if s == v {
			return true
		}
	}
	return false
}

// pythonRepr renders a Go value as a Python literal (str(dict) style).
func pythonRepr(v interface{}) string {
	switch vv := v.(type) {
	case map[string]interface{}:
		var sb strings.Builder
		sb.WriteString("{")
		keys := sortedKeys(vv)
		for i, k := range keys {
			if i > 0 {
				sb.WriteString(", ")
			}
			sb.WriteString("'")
			sb.WriteString(k)
			sb.WriteString("': ")
			sb.WriteString(pythonRepr(vv[k]))
		}
		sb.WriteString("}")
		return sb.String()
	case []interface{}:
		var sb strings.Builder
		sb.WriteString("[")
		for i, x := range vv {
			if i > 0 {
				sb.WriteString(", ")
			}
			sb.WriteString(pythonRepr(x))
		}
		sb.WriteString("]")
		return sb.String()
	case string:
		return "'" + vv + "'"
	case bool:
		if vv {
			return "True"
		}
		return "False"
	case nil:
		return "None"
	case float64:
		// JSON numbers come back as float64; render integers without trailing .0
		if vv == float64(int64(vv)) {
			return fmt.Sprintf("%d", int64(vv))
		}
		return fmt.Sprintf("%g", vv)
	default:
		return fmt.Sprintf("%v", vv)
	}
}

func jsonDumps(v interface{}) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "null"
	}
	return string(b)
}

func getByRef(ref string, data interface{}) interface{} {
	if !strings.HasPrefix(ref, "#/") {
		return nil
	}
	parts := strings.Split(ref[2:], "/")
	var index interface{} = data
	for _, p := range parts {
		m := asMap(index)
		if m == nil {
			return nil
		}
		index = m[p]
	}
	return index
}

func pVal(val map[string]interface{}) string {
	if r, ok := val["$ref"].(string); ok {
		return r
	}
	if n, ok := val["name"].(string); ok {
		return n
	}
	return ""
}

// regex helpers used during static schema inspection
var (
	urlExamplePattern  = regexp.MustCompile(`(https://)|(www.)|(.com)`)
	dateTimePattern    = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z`)
)

// ---------- templateFunction ----------

type templateFunction struct {
	json         map[string]interface{}
	security     map[string]interface{}
	body         []map[string]interface{}
	function     string
	listedParams string
}

func newTemplateFunction(j map[string]interface{}, security map[string]interface{}) *templateFunction {
	t := &templateFunction{json: j, security: security}
	t.fheader()
	return t
}

func (t *templateFunction) ebody() string {
	u := []string{}
	strJson := map[string]interface{}{}

	for _, item := range t.body {
		in := asString(item["in"])
		if !containsStr(u, in) {
			u = append(u, in)
		}
	}

	for _, j := range u {
		all := strings.Split(j, "/")
		var k []string
		if len(all) > 0 {
			k = all[1:]
		}
		var temp interface{} = strJson
		for idx, l := range k {
			if l == "items" {
				continue
			}
			hasNext := idx+1 < len(k)
			nextNotItems := hasNext && k[idx+1] != "items"
			isLast := idx+1 == len(k)
			if nextNotItems || isLast {
				if m := asMap(temp); m != nil {
					if _, exists := m[l]; !exists {
						m[l] = map[string]interface{}{}
					}
					temp = m[l]
				}
			} else if hasNext && k[idx+1] == "items" {
				if m := asMap(temp); m != nil {
					m[l] = []interface{}{}
				}
			}
		}

		if containsStr(k, "items") {
			cnsldjson := map[string]interface{}{
				"name":   k[len(k)-2],
				"isReq":  false,
				"in":     j,
				"schema": map[string]interface{}{"items": map[string]interface{}{}},
			}

			rem := map[int]bool{}
			for i, item := range t.body {
				if asString(item["in"]) != j {
					continue
				}
				schema := asMap(item["schema"])
				if schema == nil {
					continue
				}
				if _, hasItems := schema["items"]; !hasItems {
					// deep copy via json round-trip
					var copyItem map[string]interface{}
					b, _ := json.Marshal(item)
					_ = json.Unmarshal(b, &copyItem)
					delete(copyItem, "name")
					delete(copyItem, "in")
					cnsldjson["schema"].(map[string]interface{})["items"].(map[string]interface{})[asString(item["name"])] = copyItem
					rem[i] = true
				} else {
					cnsldjson["schema"].(map[string]interface{})["items"] = schema["items"]
				}
			}

			if len(rem) > 0 {
				newBody := make([]map[string]interface{}, 0, len(t.body))
				for i, item := range t.body {
					if !rem[i] {
						newBody = append(newBody, item)
					}
				}
				newBody = append(newBody, cnsldjson)
				t.body = newBody
			}
		}
	}

	return pythonRepr(strJson)
}

// dparam generates a Python validation expression for a parameter.
func (t *templateFunction) dparam(njson map[string]interface{}, ifReq bool) string {
	schema := asMap(njson["schema"])
	if schema == nil {
		schema = map[string]interface{}{}
	}
	if items, ok := schema["items"].(map[string]interface{}); ok {
		schema = items
	}
	name := asString(njson["name"])
	var r strings.Builder

	if typ, ok := schema["type"].(string); ok {
		switch {
		case strings.Contains(typ, "string"):
			r.WriteString("isinstance(" + name + ",str) and ")
		case typ == "number" || typ == "integer" || typ == "int":
			r.WriteString("isinstance(" + name + ",int) and ")
		case strings.Contains(typ, "bool"):
			r.WriteString("isinstance(" + name + ",bool) and ")
		case strings.Contains(typ, "object"):
			r.WriteString("isinstance(" + name + ",dict) and ")
			if props, ok := schema["properties"].(map[string]interface{}); ok {
				for _, key := range sortedKeys(props) {
					sub := map[string]interface{}{
						"name":   name + "['" + key + "']",
						"isReq":  njson["isReq"],
						"schema": props[key],
					}
					r.WriteString(t.dparam(sub, false) + " and ")
				}
			}
		}
	}

	if format, ok := schema["format"].(string); ok {
		// Order preserved from upstream Python (note: 'date' substring matches 'date-time' too — same behavior)
		switch {
		case strings.Contains(format, "uuid"):
			r.WriteString(`re.match("^[0-9a-zA-Z]{8}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{12}",` + name + `) != None and `)
		case strings.Contains(format, "date"):
			r.WriteString(`re.match("^[0-9]{4}-[0-9]{2}-[0-9]{2}",` + name + `) != None and `)
		case strings.Contains(format, "date-time"):
			r.WriteString(`re.match("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z",` + name + `) != None and `)
		case strings.Contains(format, "ipv4"):
			r.WriteString(`re.match("(?:[0-9]{1,3}\.){3}[0-9]{1,3}",` + name + `) != None and `)
		}
	}

	if ex, ok := schema["example"]; ok {
		exStr := fmt.Sprintf("%v", ex)
		format, _ := schema["format"].(string)
		if urlExamplePattern.MatchString(exStr) {
			r.WriteString(`re.match("(https://)|(www.)|(.com)",str(` + name + `)) != None and `)
		} else if dateTimePattern.MatchString(exStr) && format != "date-time" {
			r.WriteString(`re.match("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z",` + name + `) != None and `)
		}
	}

	if enum, ok := schema["enum"].([]interface{}); ok {
		r.WriteString(name + " in " + pythonRepr(enum) + " and ")
	}

	out := r.String()
	if len(out) >= 5 {
		out = out[:len(out)-5]
	}

	if reqRaw, ok := njson["isReq"]; ok && !asBool(reqRaw) && !ifReq {
		out = "(" + out + ") or " + name + " == None"
	}
	out = "(" + out + ")"
	return out
}

func (t *templateFunction) fheader() {
	url := asString(t.json["url"])
	urlvarend := `"` + strings.ReplaceAll(strings.ReplaceAll(url, "{", `" + `), "}", ` + "`)
	urlvar := "\turl+=" + urlvarend
	if strings.HasSuffix(urlvar, ` + "`) {
		urlvar = urlvar[:len(urlvar)-4]
		urlvarend = urlvarend[:len(urlvarend)-4]
	} else {
		urlvar += `"`
		urlvarend += `"`
	}

	queryVar := "requests." + asString(t.json["httpMode"]) + "(self.baseurl + url"
	queryVar += ", **self._apply_security({'headers': {}, 'params': {}})"

	parameters := asSlice(t.json["parameters"])

	oid := asString(t.json["oid"])

	if len(parameters) > 0 {
		t.function = ""

		tbools := "\turl=\"\"\n\t\tif("
		qbools := "\t\tmyquery={}\n\t"
		ibbools := "\t\tmybody="
		var inPath, inQuery, inBody bool
		t.body = nil
		unique := []string{}
		banned := []string{"type", "id"}

		checkBanned := func(inc map[string]interface{}) {
			if containsStr(banned, asString(inc["name"])) {
				inc["nickname"] = inc["name"]
				inc["name"] = "obj" + asString(inc["name"])
			}
		}
		// returns "" if unique, otherwise the renamed value
		chkunique := func(inc map[string]interface{}) string {
			n := asString(inc["name"])
			if !containsStr(unique, n) {
				unique = append(unique, n)
				return ""
			}
			in := asString(inc["in"])
			if strings.Contains(in, "/") {
				return in[strings.LastIndex(in, "/")+1:] + "_" + n
			}
			return in + "_" + n
		}

		for _, raw := range parameters {
			sj := asMap(raw)
			if sj == nil {
				continue
			}
			checkBanned(sj)
			in := asString(sj["in"])
			switch {
			case in == "path":
				inPath = true
				original := asString(sj["name"])
				if r := chkunique(sj); r != "" {
					sj["name"] = r
				}
				if asString(sj["name"]) != original {
					urlvar = strings.ReplaceAll(urlvar, original, asString(sj["name"]))
				}
				tbools += t.dparam(sj, false) + " and "
			case in == "query":
				inQuery = true
				if r := chkunique(sj); r != "" {
					sj["name"] = r
				}
				q := t.dparam(sj, true)
				qbools += "\tif(" + q + "):\n\t\t\t\tmyquery['" + asString(sj["name"]) + "']=" + asString(sj["name"]) + "\n\t"
			case strings.HasPrefix(in, "body"):
				inBody = true
				if r := chkunique(sj); r != "" {
					sj["name"] = r
				}
				t.body = append(t.body, sj)
			}
		}

		if inPath {
			tbools = strings.TrimSuffix(tbools, " and ") + "):\n"
			t.function += "\t" + tbools + "\t\t" + urlvar + "\t"
			t.function += "\n\t\telse:\n\t\t\traise ValueError('Error with path parameters')\n"
		} else {
			t.function += "\t\turl =" + urlvarend + "\n"
		}

		if inQuery {
			// python does qbools[:-2] which strips a trailing "\t"
			if len(qbools) >= 2 {
				qbools = qbools[:len(qbools)-2]
			}
			t.function += qbools + "\n"
			queryVar += ", params=myquery"
		}

		if inBody {
			ibbools += t.ebody() + "\n\t"
			for _, i := range t.body {
				inField := asString(i["in"])
				temp := strings.Split(inField, "/")
				temp1 := "\tmybody['"
				if len(temp) > 2 {
					for _, a := range temp[1 : len(temp)-1] {
						temp1 = temp1 + a + "']['"
					}
				}
				last := temp[len(temp)-1]
				if last != "items" {
					ibbools += "\tif(" + t.dparam(i, true) + "):\n\t\t"
					if _, has := i["nickname"]; !has {
						ibbools += temp1 + asString(i["name"]) + "']=" + asString(i["name"]) + "\n\t"
					} else {
						ibbools += temp1 + asString(i["nickname"]) + "']=" + asString(i["name"]) + "\n\t"
					}
				} else {
					if !asBool(i["isReq"]) {
						ibbools += "\tif(" + asString(i["name"]) + " != None):\n\t\t\tfor i in " + asString(i["name"]) + ":\n\t\t\t"
					} else {
						ibbools += "\tfor i in " + asString(i["name"]) + ":\n\t\t"
					}
					schema := asMap(i["schema"])
					items := asMap(schema["items"])
					if items == nil {
						items = map[string]interface{}{}
					}
					if _, has := items["type"]; has {
						sub := map[string]interface{}{
							"name":   asString(i["name"]),
							"isReq":  i["isReq"],
							"schema": items,
						}
						trim := temp1
						if len(trim) >= 2 {
							trim = trim[:len(trim)-2]
						}
						ibbools += "\tif(" + t.dparam(sub, true) + "):\n\t\t\t\t" + trim + ".append(i)\n\t"
					} else {
						ibbools += "\tif("
						for _, j := range sortedKeys(items) {
							inner := asMap(items[j])
							if inner == nil {
								continue
							}
							sub := map[string]interface{}{
								"name":   "i['" + j + "']",
								"isReq":  inner["isReq"],
								"schema": inner["schema"],
							}
							ibbools += t.dparam(sub, true) + " and "
						}
						ibbools = strings.TrimSuffix(ibbools, " and ")
						trim := temp1
						if len(trim) >= 2 {
							trim = trim[:len(trim)-2]
						}
						ibbools += "):\n\t\t\t\t" + trim + ".append(i)\n\t"
					}
				}
			}
			if len(ibbools) > 0 {
				ibbools = ibbools[:len(ibbools)-1]
			}
			queryVar += ", json=mybody"
			t.function += ibbools
		}

		t.listParams()
		t.function = "\tdef " + oid + "(self," + t.listedParams + "):\n" + t.function + "\t\treturn " + queryVar + ")"
	} else {
		t.function = "\tdef " + oid + "(self):\n"
		t.function += "\t\turl = " + urlvarend + "\n"
		queryVar = "\t\treturn requests." + asString(t.json["httpMode"]) + "(self.baseurl + url"
		queryVar += ", **self._apply_security({'headers': {}, 'params': {}}))"
		t.function += queryVar
	}
}

func (t *templateFunction) listParams() {
	addon := func(j map[string]interface{}) string {
		if reqRaw, ok := j["isReq"]; ok && !asBool(reqRaw) {
			return "=None"
		}
		return ""
	}
	temp := []string{}
	for _, raw := range asSlice(t.json["parameters"]) {
		i := asMap(raw)
		if i == nil {
			continue
		}
		if !strings.HasPrefix(asString(i["in"]), "body") {
			temp = append(temp, asString(i["name"])+addon(i)+",")
		}
	}
	for _, i := range t.body {
		temp = append(temp, asString(i["name"])+addon(i)+",")
	}
	// Stable sort: required params first, optional (=None) last.
	sort.SliceStable(temp, func(a, b int) bool {
		ai := strings.Contains(temp[a], "=None")
		bi := strings.Contains(temp[b], "=None")
		if ai == bi {
			return false
		}
		return !ai
	})
	t.listedParams = strings.Join(temp, "")
	if strings.HasSuffix(t.listedParams, ",") {
		t.listedParams = t.listedParams[:len(t.listedParams)-1]
	}
}

// ---------- myEval ----------

type myEval struct {
	mjson      map[string]interface{}
	sec        map[string]interface{}
	processing map[string]interface{}
	GenClass   string
	Title      string
}

func (e *myEval) inProcessing(name string, isReq bool, myin string, schema interface{}) {
	item := map[string]interface{}{
		"name":   name,
		"isReq":  isReq,
		"in":     nil,
		"schema": schema,
	}
	if myin != "" {
		item["in"] = myin
	}
	if sm := asMap(schema); sm != nil {
		if _, ok := sm["required"]; ok {
			delete(sm, "required")
			delete(sm, "in")
		}
	}
	params := asSlice(e.processing["parameters"])
	params = append(params, item)
	e.processing["parameters"] = params
}

func (e *myEval) caseName(mjson map[string]interface{}) {
	isReq := false
	myin := ""
	if v, ok := mjson["in"].(string); ok {
		myin = v
	}
	if v, ok := mjson["required"].(bool); ok {
		isReq = v
	} else if props, ok := mjson["properties"].(map[string]interface{}); ok {
		if reqList, ok := props["required"].([]interface{}); ok {
			name := pVal(mjson)
			for _, r := range reqList {
				if asString(r) == name {
					isReq = true
					break
				}
			}
		}
	}
	e.inProcessing(pVal(mjson), isReq, myin, mjson["schema"])
}

func (e *myEval) caseItems(mjson map[string]interface{}, myin string, requiredSet bool, requiredVal bool, propname string) {
	temp := propname + "/items"
	if myin != "" {
		temp = myin + "/" + propname + "/items"
	}

	isReq := false
	if reqList, ok := mjson["required"].([]interface{}); ok {
		for _, r := range reqList {
			if asString(r) == propname {
				isReq = true
				break
			}
		}
	} else if props, ok := mjson["properties"].(map[string]interface{}); ok {
		if reqList, ok := props["required"].([]interface{}); ok {
			for _, r := range reqList {
				if asString(r) == propname {
					isReq = true
					break
				}
			}
		}
	}
	if requiredSet {
		isReq = requiredVal
	}

	if props, ok := mjson["properties"].(map[string]interface{}); ok {
		prop := asMap(props[propname])
		if prop == nil {
			return
		}
		items := asMap(prop["items"])
		if items == nil {
			return
		}
		if _, has := items["$ref"]; has {
			e.casedref(items, temp, true, isReq)
		} else if _, has := items["enum"]; has {
			e.inProcessing(propname, isReq, temp, map[string]interface{}{"items": items})
		} else if _, has := items["properties"]; !has {
			e.inProcessing(propname, isReq, temp, map[string]interface{}{"items": items})
		} else {
			e.caseProperties(items, temp, true, isReq)
		}
	} else if items, ok := mjson["items"].(map[string]interface{}); ok {
		if _, has := items["$ref"]; has {
			e.casedref(items, temp, true, isReq)
		}
	}
}

func (e *myEval) caseProperties(mjson map[string]interface{}, myin string, requiredSet bool, requiredVal bool) {
	props, ok := mjson["properties"].(map[string]interface{})
	if !ok {
		return
	}
	for _, b := range sortedKeys(props) {
		entry := asMap(props[b])
		if entry == nil {
			continue
		}
		if _, has := entry["$ref"]; has {
			temp := b
			if myin != "" {
				temp = myin + "/" + b
			}
			c := e.casedref(entry, temp, requiredSet, requiredVal)
			if cm := asMap(c); cm != nil {
				if _, ok := cm["enum"]; ok {
					isReq := false
					if reqList, ok := mjson["required"].([]interface{}); ok {
						for _, r := range reqList {
							if asString(r) == b {
								isReq = true
								break
							}
						}
					}
					if requiredSet && requiredVal {
						isReq = true
					}
					e.inProcessing(b, isReq, myin, cm)
				}
			}
		} else if _, has := entry["items"]; has {
			e.caseItems(mjson, myin, requiredSet, requiredVal, b)
		} else {
			useIn := myin
			if v, ok := entry["in"].(string); ok {
				useIn = v
			}
			isReq := false
			if reqList, ok := mjson["required"].([]interface{}); ok {
				for _, r := range reqList {
					if asString(r) == b {
						isReq = true
						break
					}
				}
			} else if pmap, ok := mjson["properties"].(map[string]interface{}); ok {
				if reqList, ok := pmap["required"].([]interface{}); ok {
					for _, r := range reqList {
						if asString(r) == b {
							isReq = true
							break
						}
					}
				}
			}
			if requiredSet && requiredVal {
				isReq = true
			}
			e.inProcessing(b, isReq, useIn, entry)
		}
	}
}

func (e *myEval) caseParameters(mjson map[string]interface{}) {
	s := mjson["parameters"]
	if sm := asMap(s); sm != nil {
		if _, has := sm["$ref"]; has {
			e.casedref(sm, "", false, false)
			return
		}
	}
	if list := asSlice(s); list != nil {
		for _, m := range list {
			mm := asMap(m)
			if mm == nil {
				continue
			}
			if _, has := mm["$ref"]; has {
				e.casedref(mm, "", false, false)
			} else {
				e.caseName(mm)
			}
		}
	}
}

func (e *myEval) caseoneOf(mjson map[string]interface{}, myin string, required bool) interface{} {
	inner := mjson["oneOf"]
	innerMap := asMap(inner)
	if innerMap == nil {
		// oneOf is typically a list per spec; the upstream Python treated it as a dict, so mirror behavior on a map
		// fall through to returning whatever it is.
		return inner
	}
	if _, has := innerMap["oneOf"]; has {
		// spec calls for list-of-schemas — best-effort recursion
		for _, a := range asSlice(innerMap["oneOf"]) {
			if am := asMap(a); am != nil {
				e.caseoneOf(am, myin, required)
			}
		}
	} else if _, has := innerMap["$ref"]; has {
		e.casedref(innerMap, myin, true, required)
	} else {
		return innerMap
	}
	return nil
}

func (e *myEval) caseallOf(mjson map[string]interface{}, myin string, required bool) interface{} {
	all := asSlice(mjson["allOf"])
	for _, raw := range all {
		p := asMap(raw)
		if p == nil {
			continue
		}
		if _, has := p["allOf"]; has {
			for _, a := range asSlice(p["allOf"]) {
				if am := asMap(a); am != nil {
					e.caseallOf(am, myin, required)
				}
			}
		} else if _, has := p["properties"]; has {
			e.caseProperties(p, myin, true, required)
		} else if _, has := p["oneOf"]; has {
			c := e.caseoneOf(p, myin, required)
			if c != nil {
				if disc := asMap(p["discriminator"]); disc != nil {
					if mapping := asMap(disc["mapping"]); mapping != nil {
						for _, d := range sortedKeys(mapping) {
							e.casedref(map[string]interface{}{"$ref": asString(mapping[d])}, myin+"/"+d, true, false)
						}
					}
				}
			}
		}
	}
	return nil
}

func (e *myEval) casedref(mjson map[string]interface{}, myin string, requiredSet bool, requiredVal bool) interface{} {
	ref := pVal(mjson)
	resolved := asMap(getByRef(ref, e.mjson))
	if resolved == nil {
		return nil
	}
	parts := strings.Split(ref, "/")
	if _, has := resolved["properties"]; has {
		e.caseProperties(resolved, myin, requiredSet, requiredVal)
	} else if _, has := resolved["allOf"]; has {
		e.caseallOf(resolved, myin, requiredVal)
	} else if _, has := resolved["name"]; has {
		e.caseName(resolved)
	} else if _, has := resolved["items"]; has {
		e.caseItems(resolved, myin, requiredSet, requiredVal, parts[len(parts)-1])
	} else if _, has := resolved["enum"]; has {
		return resolved
	} else {
		return resolved
	}
	return nil
}

func (e *myEval) caseRQbody(mjson map[string]interface{}) {
	rb := asMap(mjson["requestBody"])
	if rb == nil {
		return
	}
	required := false
	if _, has := rb["required"]; has {
		required = true
	}
	content := asMap(rb["content"])
	if content == nil {
		return
	}
	var schemaParent map[string]interface{}
	for _, ct := range []string{"application/json", "application/x-www-form-urlencoded", "multipart/form-data"} {
		if v := asMap(content[ct]); v != nil {
			schemaParent = asMap(v["schema"])
			break
		}
	}
	if schemaParent == nil {
		return
	}
	if _, has := schemaParent["$ref"]; has {
		e.casedref(schemaParent, "body", true, required)
		return
	}
	if props, ok := schemaParent["properties"].(map[string]interface{}); ok {
		for _, p := range sortedKeys(props) {
			pm := asMap(props[p])
			if pm == nil {
				continue
			}
			pm["in"] = "body"
			pm["required"] = required
		}
		e.caseProperties(schemaParent, "body", true, required)
	}
}

func (e *myEval) caseOID(mjson map[string]interface{}) {
	for _, l := range sortedKeys(mjson) {
		if l == "parameters" {
			e.caseParameters(mjson)
		}
		if l == "requestBody" {
			e.caseRQbody(mjson)
		}
	}
}

// ensureOperationIds adds synthetic operationIds where missing, matching swaggertopy_external.py.
func ensureOperationIds(mjson map[string]interface{}) {
	paths := asMap(mjson["paths"])
	if paths == nil {
		return
	}
	unique := map[string]bool{}
	for _, key := range sortedKeys(paths) {
		ops := asMap(paths[key])
		if ops == nil {
			continue
		}
		for _, kp := range sortedKeys(ops) {
			op := asMap(ops[kp])
			if op == nil {
				continue
			}
			if _, has := op["operationId"]; !has {
				op["operationId"] = ""
			}
			oid := asString(op["operationId"])
			if oid == "" {
				oid = kp + "_" + strings.ReplaceAll(strings.TrimPrefix(key, "/"), "/", "_")
				oid = strings.ReplaceAll(oid, "{", "")
				oid = strings.ReplaceAll(oid, "}", "")
				op["operationId"] = oid
			}
			if unique[oid] {
				i := 0
				for unique[oid+fmt.Sprintf("%d", i)] {
					i++
				}
				oid = oid + fmt.Sprintf("%d", i)
				op["operationId"] = oid
			}
			unique[oid] = true
		}
	}
}

const applySecurityMethod = `
	def _apply_security(self, request_params):
		if not self.security_config:
			return request_params

		headers = request_params.get('headers', {})
		params = request_params.get('params', {})

		for security_type, credentials in self.security_config.items():
			if security_type == 'BasicAuth':
				request_params['auth'] = (credentials['username'], credentials['password'])
			elif security_type == 'BearerAuth':
				headers['Authorization'] = f"Bearer {credentials['token']}"
			elif security_type == 'ApiKeyAuth':
				if credentials['in'] == 'header':
					headers[credentials['name']] = credentials['value']
				elif credentials['in'] == 'query':
					params[credentials['name']] = credentials['value']
				elif credentials['in'] == 'cookie':
					request_params['cookies'] = {credentials['name']: credentials['value']}
			elif security_type == 'ApiKeyAuthSecret':
				headers[credentials['name']] = credentials['value']
			elif security_type == 'OAuth2':
				headers['Authorization'] = f"Bearer {credentials['access_token']}"
			elif security_type == 'OpenIDConnect':
				headers['Authorization'] = f"Bearer {credentials['id_token']}"

		request_params['headers'] = headers
		request_params['params'] = params
		return request_params
	`

func newMyEval(jsonStr string) (*myEval, error) {
	dec := json.NewDecoder(bytes.NewReader([]byte(jsonStr)))
	dec.UseNumber()
	var raw interface{}
	if err := dec.Decode(&raw); err != nil {
		return nil, fmt.Errorf("parse swagger json: %w", err)
	}
	// convert json.Number values to float64 to keep behavior simple
	mjson := normalizeNumbers(raw).(map[string]interface{})

	e := &myEval{mjson: mjson}

	if comps := asMap(mjson["components"]); comps != nil {
		if sec := asMap(comps["securitySchemes"]); sec != nil {
			e.sec = sec
		}
	}

	ensureOperationIds(mjson)

	title := "swagger"
	if info := asMap(mjson["info"]); info != nil {
		if t, ok := info["title"].(string); ok && t != "" {
			title = t
		}
	}
	className := strings.ReplaceAll(title, " ", "_")

	var sb strings.Builder
	sb.WriteString("class " + className + ":\n")

	outer := "\tdef __init__(self,"
	inner := ""
	if e.sec != nil {
		outer += "security_config=None,"
		inner += "\t\tself.security_config = security_config or {}\n"
	}

	servers := asSlice(mjson["servers"])
	if len(servers) > 1 {
		outer += "server=None,"
		inner += "\t\tself.servers = ["
		for i, s := range servers {
			if i > 0 {
				inner += ","
			}
			inner += jsonDumps(s)
		}
		inner += "]\n"
		inner += "\t\tif(server is not None and isinstance(server, int)):\n"
		inner += "\t\t\tself.baseurl = self.servers[server]['url']\n"
		inner += "\t\telse:\n\t\t\tself.baseurl = self.servers[0]['url']\n"
	} else if len(servers) == 1 {
		first := asMap(servers[0])
		inner += "\t\tself.baseurl = " + jsonDumps(first["url"]) + "\n"
	} else {
		inner += "\t\tself.baseurl = \"\"\n"
	}

	if strings.HasSuffix(outer, ",") {
		outer = outer[:len(outer)-1]
	}
	sb.WriteString(outer + "):\n" + inner)
	sb.WriteString(applySecurityMethod)

	paths := asMap(mjson["paths"])
	if paths != nil {
		for _, key := range sortedKeys(paths) {
			ops := asMap(paths[key])
			if ops == nil {
				continue
			}
			for _, op := range sortedKeys(ops) {
				operation := asMap(ops[op])
				if operation == nil {
					continue
				}
				e.processing = map[string]interface{}{"parameters": []interface{}{}}
				if oid, ok := operation["operationId"].(string); ok {
					e.processing["oid"] = strings.ReplaceAll(oid, "-", "_")
				}
				e.caseOID(operation)
				e.processing["httpMode"] = op
				e.processing["url"] = key
				fn := newTemplateFunction(e.processing, e.sec)
				sb.WriteString("\n" + fn.function)
			}
		}
	}

	e.GenClass = "import json\nimport re\nimport requests\n" + sb.String()
	e.Title = className + ".py"
	return e, nil
}

// normalizeNumbers walks the parsed tree and turns json.Number into float64
// so downstream code can rely on plain interface{} types.
func normalizeNumbers(v interface{}) interface{} {
	switch vv := v.(type) {
	case map[string]interface{}:
		out := make(map[string]interface{}, len(vv))
		for k, x := range vv {
			out[k] = normalizeNumbers(x)
		}
		return out
	case []interface{}:
		out := make([]interface{}, len(vv))
		for i, x := range vv {
			out[i] = normalizeNumbers(x)
		}
		return out
	case json.Number:
		if i, err := vv.Int64(); err == nil {
			return float64(i)
		}
		if f, err := vv.Float64(); err == nil {
			return f
		}
		return vv.String()
	default:
		return v
	}
}
