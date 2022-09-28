
from js import (
  document,
  console
)
import js
from pyodide import create_proxy



import json
import re

def getbyref(ref,data):
	temp = ref[2:].split('/')
	index = data
	for t in temp:
		index = index[t]
	return index

def pVal(val):
	if('$ref' in val):
		return val['$ref']
	elif('name' in val):
		return val['name']



class templateFunction:
	def ebody(self):
		u = []
		strJson = {}
		for i in self.body:
			if(i['in'] not in u):
				u.append(i['in'])
		for j in u:
			k = j.split('/')[1:]
			temp = strJson
			for l in k:
				if(l!='items'):
					if((k.index(l)+1 < len(k) and k[k.index(l)+1] != 'items') or k.index(l)+1 == len(k)):
						if(l not in temp):
							temp[l] = {}
						temp = temp[l]
					elif(k.index(l)+1 < len(k) and k[k.index(l)+1] == 'items'):
						temp[l] = []
			if('items' in k):
				cnsldjson = {'name':k[len(k)-2],'isReq':False if 'requiredRB' in self.json and self.json['requiredRB'] == True else False,'in':j,'schema':{'items':{}}}
				rem = []
				for i in self.body:
					if(i['in'] == j):
						if('items' not in i['schema']):
							cnsldjson['schema']['items'][i['name']] = json.loads(json.dumps(i))
							del cnsldjson['schema']['items'][i['name']]['name']
							del cnsldjson['schema']['items'][i['name']]['in']
							rem.append(i)
						elif('items' in i['schema']):
							cnsldjson['schema']['items'] = i['schema']['items']
	
				
				for i in rem:
					self.body.remove(i)
				if(rem != []):
					self.body.append(cnsldjson)
					
		return str(strJson)
	def dparam(self,njson,ifReq=False):
		r = ''
		if('items' in njson['schema']):
			njson['schema'] = njson['schema']['items']
		if('type' in njson['schema']):
			if('string' in njson['schema']['type']):
				r += 'isinstance('+njson['name']+',str) and '
			elif(njson['schema']['type'] in ['number','integer','int']):
				r += 'isinstance('+njson['name']+',int) and '
			elif('bool' in njson['schema']['type']):
				r+= 'isinstance('+njson['name']+',bool) and '
			elif('object' in njson['schema']['type']):
				r += 'isinstance('+njson['name'] +',dict) and ' 
				if('properties' in njson['schema']):
					for i in njson['schema']['properties']:	
						r += self.dparam({'name':njson['name'] + "['" + i + "']",'isReq':njson['isReq'],'schema':njson['schema']['properties'][i]}) + ' and '
		if('format' in njson['schema']):
			if('uuid' in njson['schema']['format']):
				 r += 're.match("^[0-9a-zA-Z]{8}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{4}-[0-9a-zA-Z]{12}",' + njson['name'] + ') != None and '
			elif('date' in njson['schema']['format']):
				r += 're.match("^[0-9]{4}-[0-9]{2}-[0-9]{2}",' + njson['name'] + ') != None and '
			elif('date-time' in njson['schema']['format']):
				r += 're.match("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z",' + njson['name'] + ') != None and '
			elif('ipv4' in njson['schema']['format']):
				r += 're.match("(?:[0-9]{1,3}\.){3}[0-9]{1,3}",' + njson['name'] + ') != None and '
		if('example' in njson['schema']):
			if(re.match('(https://)|(www.)|(.com)',str(njson['schema']['example']))):
				r += 're.match("(https://)|(www.)|(.com)",str(' + njson['name'] + ')) != None and '
			elif(re.match("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z",str(njson['schema']['example'])) and ('format' not in njson['schema'] or njson['schema']['format'] != 'date-time')):
				r += 're.match("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z",' + njson['name'] + ') != None and '
		if('enum' in njson['schema']):
			r += njson['name'] + ' in ' + str(njson['schema']['enum']) + ' and '
		r = r[:-5]
		if('isReq' in njson and njson['isReq'] == False and ifReq == False):
			r = "(" + r + ") or " + njson['name'] + " == None" 
		
		r = "(" + r + ")"
		
		return r
	def fheader(self):
		
		
		urlvarend = '"'+ self.json['url'].replace('{','" + ').replace('}',' + "')
		urlvar = '\turl+='+ urlvarend
		if(urlvar[len(urlvar)-4:] == ' + "'):
			urlvar = urlvar[:-4]
			urlvarend = urlvarend[:-4]
		else:
			urlvar += '"'
			urlvarend += '"'
		
		qvar = '\tmyquery={'
		queryVar = "return requests." + self.json['httpMode'] + "("
		queryVar += 'self.baseurl + url'
		
		if(len(self.json['parameters']) > 0):
			self.function = ""
			
			tbools = '\turl=""\n\t\tif('
			qbools = '\t\tmyquery={}\n\t'
			ibbools = '\t\tmybody='
			paramies = {}
			paramies['inPath'] = False
			paramies['inQuery'] = False
			paramies['inBody'] = False
			self.body = []
			unique = []
			banned = ['type','id']
			def checkBanned(inc):
				if(inc['name'] in banned):
					inc['nickname'] = inc['name']
					inc['name'] = 'obj' + inc['name']
			def chkunique(inc):
				if(inc['name'] not in unique):
					unique.append(inc['name'])
					return False
				else:
					if('/' in inc['in']):
						return inc['in'][inc['in'].rindex('/') + 1:] + '_' + inc['name']
					else:
						return inc['in'] + '_' + inc['name']
			for sj in self.json['parameters']:
				checkBanned(sj)
				if(sj['in'] == 'path'):
					paramies['inPath'] = True
					temp = sj['name']
					sj['name'] = sj['name'] if not chkunique(sj) else chkunique(sj)
					if(temp != sj['name']):
						urlvar = urlvar.replace(temp,sj['name']);
					t = self.dparam(sj)
					tbools += t + ' and '		
				elif(sj['in'] == 'query'):
					paramies['inQuery'] = True
					sj['name'] = sj['name'] if not chkunique(sj) else chkunique(sj)
					q = self.dparam(sj,True)
					qbools += "\tif(" + q + "):\n\t\t\t\tmyquery['" + sj['name'] + "']=" + sj['name'] + "\n\t"
				elif(sj['in'][:4] == 'body'):
					paramies['inBody'] = True
					sj['name'] = sj['name'] if not chkunique(sj) else chkunique(sj)
					self.body.append(sj)
			
		
			if(paramies['inPath']):
				tbools = tbools[:-5] + '):\n'
				self.function += "\t" + tbools + '\t\t' + urlvar + '\t'
				self.function += "\n\t\telse:\n\t\t\traise ValueError('Error with path parameters')\n"	
			else:
				self.function += "\t\turl =" + urlvarend + "\n"
				
			if(paramies['inQuery']):
				self.function += qbools[:-2] + '\n'
				queryVar += ", params=myquery"
			
			if(paramies['inBody']):
				ibbools += self.ebody() + "\n\t"
				inbod = ''
				for i in self.body:
					temp = i['in'].split('/')
					temp1 = "\tmybody['"
					for a in temp[1:-1]: temp1 = temp1 + a + "']['" 
					if(temp[len(temp)-1] != 'items'):
						ibbools += "\tif(" + self.dparam(i,True) + "):\n\t\t"
						if("nickname" not in i): 
							ibbools += temp1 + i['name'] + "']=" + i['name'] + "\n\t" 
						else:
							ibbools += temp1 + i['nickname'] + "']=" + i['name'] + "\n\t" 
						inbod += temp1
						
					else:
						if(i["isReq"] == False):
							ibbools += '\tif(' + i["name"] + " != None):\n\t\t\tfor i in " + i["name"] + ":\n\t\t\t"
						else:
							ibbools += "\tfor i in " + i["name"] + ":\n\t\t"
						if("type" in i['schema']['items']):
							ibbools += "\tif(" + self.dparam({"name":i["name"],"isReq":["isReq"],"schema":i["schema"]["items"]},True) + "):\n\t\t\t\t" + temp1[:-2] + ".append(i)\n\t"
						else:
							ibbools += "\tif("
							for j in i['schema']['items']:
								ibbools += self.dparam({"name":"i['"+j+"']","isReq":i['schema']['items'][j]['isReq'],"schema":i['schema']['items'][j]['schema']},True) + " and "
							ibbools = ibbools[:-5] + "):\n\t\t\t\t" + temp1[:-2] + ".append(i)\n\t" 	
				ibbools = ibbools[:-1]
				queryVar += ", json=mybody"
				self.function += ibbools
			if(self.security == {'BasicAuth': {'type': 'http', 'scheme': 'basic'}}):
				queryVar += ", auth=(self.user,self.password)"
			self.listParams()	
			self.function ='\tdef ' + self.json['oid'] + '(self,' + self.listedParams + '):\n' + self.function + "\t\t" + queryVar + ")"
			
		else:
			self.function = '\tdef ' + self.json['oid'] + '(self):\n'
			self.function +="\t\turl = " + urlvarend + "\n"
			queryVar = "\t\treturn requests." + self.json['httpMode'] + "("
			queryVar += 'self.baseurl + url'
			if(self.security == {'BasicAuth': {'type': 'http', 'scheme': 'basic'}}):
				queryVar += ", auth=(self.user,self.password)"
			self.function = self.function + queryVar + ")"
	def listParams(self):
		self.listedParams = ''
		def isAddon(j):
			addon = ''
			if('isReq' in j and j['isReq'] == False):
				addon = '=None'
			return addon
		temp = []
		for i in self.json['parameters']:
			if(i['in'][:4] != 'body'):
				temp.append(i['name'] + isAddon(i) + ',')
		for i in self.body:
			temp.append(i['name'] + isAddon(i) + ',')
		temp = sorted(temp, key=lambda x:('=None' in x))
		for i in temp:
			self.listedParams += i
		self.listedParams = self.listedParams[:-1]
		
	def __init__(self,njson,security):
		self.json = njson
		self.security = security
		self.fheader()
	

class myEval:
	def inProcessing(self,name,isReq,myin=None,schema=None):
		item = {"name":name,"isReq":isReq,"in":myin,"schema":schema}
		if(schema != None and 'required' in schema):
			del schema['required']
			del schema['in']
		self.processing['parameters'].append(item)	
	def caseName(self,mjson):
		isReq = False
		myin = None
		if('in' in mjson):
			myin = mjson['in']
		if('required' in mjson):
			isReq = mjson['required']
		elif('properties' in mjson and 'required' in mjson['properties']):
			isReq = pVal(mjson) in mjson['properties']['required']
		self.inProcessing(pVal(mjson),isReq,myin,mjson['schema'])
	def caseItems(self,mjson,myin=None,required=None,propname=None):
		temp = myin
		if(myin != None):
			temp = myin + '/' + propname + '/items'
		else:
			temp = propname + '/items'
			
		isReq = False
		if('required' in mjson):
			isReq = propname in mjson['required'] 
		elif('properties' in mjson and 'required' in mjson['properties']):
			isReq = propname in mjson['properties']['required']
		isReq = isReq if required == None else required
		
		if('properties' in mjson and '$ref' in mjson['properties'][propname]['items']):
			self.casedref(mjson['properties'][propname]['items'],temp,isReq)
		elif('properties' in mjson and 'enum' in mjson['properties'][propname]['items']):
			self.inProcessing(propname,isReq,temp,{'items':mjson['properties'][propname]['items']})
		elif('properties' in mjson and 'properties' not in mjson['properties'][propname]['items']):
			self.inProcessing(propname,isReq,temp,{'items':mjson['properties'][propname]['items']})
		elif('properties' in mjson and 'properties' in mjson['properties'][propname]['items']):
			self.caseProperties(mjson['properties'][propname]['items'],temp,isReq)
		elif('items' in mjson and '$ref' in mjson['items']):
			self.casedref(mjson['items'],temp,isReq)
	def caseProperties(self,mjson,myin=None,required=None):
		for b in mjson['properties']:
			if('$ref' in mjson['properties'][b]):
				temp = myin
				if(myin != None):
					temp = myin + '/' + b
				else:
					temp = b
				c = self.casedref(mjson['properties'][b],temp,required)
				if(c != None and 'enum' in c):
					isReq = False
					if('required' in mjson or b in mjson['required'] or required):
						isReq = True
					temp = myin
					self.inProcessing(b,isReq,temp,c)
					
			elif('items' in mjson['properties'][b]):
				self.caseItems(mjson,myin,required,b)
			else:
				myin = myin if 'in' not in mjson['properties'][b] else mjson['properties'][b]['in'] 
				isReq = False
				if('required' in mjson):
					isReq = b in mjson['required'] 
				elif('required' in mjson['properties']):
					isReq = b in mjson['properties']['required']
				isReq = isReq if not required or required == None else True			
				self.inProcessing(b,isReq,myin,mjson['properties'][b])
	def caseParameters(self,mjson):
		s = mjson['parameters']
		if('$ref' in s):
			self.casedref(s)
		elif(isinstance(s,list)):
			for m in s:
				if('$ref' in m):
					self.casedref(m)
				else:
					self.caseName(m)
		else:
			print("failure in caseParameters")
	def caseoneOf(self,mjson,myin=None,required=False):
		mjson = mjson['oneOf']
		if('oneOf' in mjson):
			for a in mjson['oneOf']:
				c = self.caseoneOf(a,myin,required)
		elif('$ref' in mjson):
			self.casedref(mjson,myin,required)
		else:
			return mjson
	def caseallOf(self,mjson,myin=None,required=False):
		mjson = mjson['allOf']
		for p in mjson:
			if('allOf' in p):
				for a in p['allOf']:
					self.caseallOf(a,myin,required)
			elif('properties' in p):
				self.caseProperties(p,myin,required)
			elif('oneOf' in p):
				c = self.caseoneOf(p,myin,required)
				if(c):
					for d in p['discriminator']['mapping']:	
						self.casedref({'$ref':p['discriminator']['mapping'][d]},myin + '/' + d,False)
			elif(isinstance(p,list)):
				for a in p:
					if('properties' in a):
						self.caseProperties(a,myin,required)
					elif('oneOf' in a):
						self.caseoneOf(a,myin,required)
					else:
						return a
			else:
				return p
	def casedref(self,mjson,myin=None,required=False):
		ref = pVal(mjson)
		mjson = getbyref(ref,self.mjson)
		ref = ref.split('/')
		if('properties' in mjson):
			self.caseProperties(mjson,myin,required)
		elif('allOf' in mjson):
			self.caseallOf(mjson,myin,required)
		elif('name' in mjson):
			self.caseName(mjson)
		elif('items' in mjson):
			self.caseItems(mjson,myin,required,ref[len(ref)-1])
		elif('enum' in mjson):
			return mjson
		else:
			return mjson
	def caseRQbody(self,mjson):
		required = False
		if('required' in mjson['requestBody']):
			required = True
		mjson = mjson['requestBody']['content']['application/json']['schema']
		if('$ref' in mjson):
			temp = mjson['$ref'][2:].split('/')
			self.casedref(mjson,'body')
		elif('properties' in mjson):
			for p in mjson['properties']:
				mjson['properties'][p]['in'] = 'body'
				mjson['properties'][p]['required'] = required
			self.caseProperties(mjson,'body',required)
	def caseOID(self,mjson):
		for l in mjson:
			if(l == "parameters"):
				self.caseParameters(mjson)
			if( l == "requestBody" ):
				self.caseRQbody(mjson)
	def __init__(self,mjson):
		unique = []
		mjson = json.loads(mjson);
		self.mjson = mjson
		for key in mjson['paths'].keys():
			for kp in mjson['paths'][key].keys():
				if(type(mjson['paths'][key][kp]) is dict):
					if('operationId' not in mjson['paths'][key][kp].keys()):
						mjson['paths'][key][kp]['operationId'] = ""
					uuid = kp + "_" + key[1:].replace('/','_') 
					while(uuid.find('{') != -1):
						uuid = uuid.replace('{','')
						uuid = uuid.replace('}','')
					mjson['paths'][key][kp]['operationId'] = uuid
					if(mjson['paths'][key][kp]['operationId'] not in unique):
						unique.append(mjson['paths'][key][kp]['operationId'])
					else:
						i = 0
						while(mjson['paths'][key][kp]['operationId'] not in unique):
							mjson['paths'][key][kp]['operationId'] = mjson['paths'][key][kp]['operationId'] + str(i)
							i+=1
						unique.append(mjson['paths'][key][kp]['operationId'])
		self.json = mjson['paths']
		self.sec = None
		if('securitySchemes' in mjson['components']):
			self.sec = mjson['components']['securitySchemes']
		self.genClass = ""
		myinit = {"outer":"\tdef __init__(self,","inner":""}
		if('info' in mjson and 'title' in mjson['info']):
			self.genClass+= "class " + mjson['info']['title'].replace(' ','_') + ":\n"
		if(self.sec == {'BasicAuth': {'type': 'http', 'scheme': 'basic'}}):
			myinit["outer"] += "username,password,"
			myinit["inner"] += "\t\tself.user=username\n\t\tself.password=password\n"
		if(len(mjson["servers"]) > 1):
			myinit["outer"] += "server=None,"
			myinit["inner"] += "\t\tself.servers = ["
			for i in mjson["servers"]:
				myinit["inner"] += json.dumps(i) + ","
			myinit["inner"] = myinit["inner"][:-1] + "]\n"
			myinit["inner"] += "\t\tif(server!=None and isinstance(server,int)):\n\t\t\tself.baseurl=self.servers[server]['url']\n\t\telse:\n\t\t\tself.baseurl=self.servers[0]['url']"
		else:
			myinit["inner"] += "\t\tself.baseurl="+json.dumps(mjson["servers"][0]['url'])
		self.genClass += myinit['outer'][:-1] + "):\n" + myinit['inner']
		myOps = []
		for j in self.json:
			self.processingGP = None
			for k in self.json[j]:
				self.processing = {'parameters':[]}
				if('operationId' in self.json[j][k]):
					self.processing['oid'] = self.json[j][k]['operationId'].replace('-','_')
					self.caseOID(self.json[j][k])
					if(self.processingGP != None):
						for item in self.processingGP['parameters']:
							self.processing['parameters'].append(item)
					self.processing['httpMode'] = k
					self.processing['url'] = j
					myOps.append(templateFunction(self.processing,self.sec))
				elif('parameters' in self.json[j].keys()):
					self.caseParameters(self.json[j])
					self.processingGP = self.processing
		
		for op in myOps:
			self.genClass +='\n' + op.function
		self.genClass = "import json\nimport re\nimport requests\n" + self.genClass
		self.title = mjson['info']['title'].replace(' ','_') + '.py'
		


def genSDK(json):
	def conJson(j,title):
		title = title.split('.');
		title = title[len(title)-1];
		output = None;
		output = myEval(j);
		js.download(output.genClass,output.title);
	js.getJson(create_proxy(conJson));
document.getElementById("submit").addEventListener("click", create_proxy(genSDK));
					


