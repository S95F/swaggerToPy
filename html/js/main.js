


function getJson(cb){
	let file = document.getElementById("myFile");
	function logFile (event) {
		let str = event.target.result;
		let json = JSON.parse(str);
		cb(str,file.files[0].name);
	}
	let reader = new FileReader();
	reader.onload = logFile;
	reader.readAsText(file.files[0]);
}
function download(text,filename) {
	var element = document.createElement('a');
	element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(text));
	element.setAttribute('download', filename);
	element.style.display = 'none';
	document.body.appendChild(element);
	element.click();
	document.body.removeChild(element);
}

window.onload = function(){
	rLsetup("typeContainer");
	rLsetup("formatContainer");
	document.getElementById("myFile").addEventListener("change", checkFile, false);
}

function rLsetup(cName){
	var tc = document.getElementById(cName).children;
	for(const t in tc){
		if((t%2) == 0){
			tc[t].classList.add('rightLine');
		}
	}
}


function checkFile(){
	var f = document.getElementById("myFile");
	f = f.files[0].name.split('.');
	f = f[f.length - 1]
	var s = document.getElementById("submit");
	if(f != "json"){
		s.disabled = true;
		s.parentElement.disabled = true;
		s.parentElement.children[1].innerHTML = "Invalid File Format!";
	}else{
		s.disabled = false;
		s.parentElement.disabled = false;
		s.parentElement.children[1].innerHTML = "";
	}
}


