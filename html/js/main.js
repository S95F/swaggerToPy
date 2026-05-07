function download(text, filename) {
	var element = document.createElement('a');
	element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(text));
	element.setAttribute('download', filename);
	element.style.display = 'none';
	document.body.appendChild(element);
	element.click();
	document.body.removeChild(element);
}

function readFileAsText(file) {
	return new Promise(function (resolve, reject) {
		var reader = new FileReader();
		reader.onload = function (e) { resolve(e.target.result); };
		reader.onerror = function () { reject(reader.error); };
		reader.readAsText(file);
	});
}

async function submitSwagger() {
	var input = document.getElementById("myFile");
	if (!input.files || input.files.length === 0) {
		return;
	}
	var file = input.files[0];
	var text;
	try {
		text = await readFileAsText(file);
	} catch (err) {
		alert("Failed to read file: " + err);
		return;
	}

	var btn = document.getElementById("submit");
	btn.disabled = true;
	var prevValue = btn.value;
	btn.value = "converting...";

	try {
		var resp = await fetch("/api/convert", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: text
		});
		if (!resp.ok) {
			var errMsg = await resp.text();
			throw new Error(errMsg || ("HTTP " + resp.status));
		}
		var data = await resp.json();
		download(data.code, data.title);
	} catch (err) {
		alert("Conversion failed: " + err.message);
	} finally {
		btn.disabled = false;
		btn.value = prevValue;
	}
}

window.onload = function () {
	rLsetup("typeContainer");
	rLsetup("formatContainer");
	document.getElementById("myFile").addEventListener("change", checkFile, false);
	document.getElementById("submit").addEventListener("click", submitSwagger, false);
};

function rLsetup(cName) {
	var tc = document.getElementById(cName).children;
	for (const t in tc) {
		if ((t % 2) == 0) {
			tc[t].classList.add('rightLine');
		}
	}
}

function checkFile() {
	var f = document.getElementById("myFile");
	f = f.files[0].name.split('.');
	f = f[f.length - 1];
	var s = document.getElementById("submit");
	if (f != "json") {
		s.disabled = true;
		s.parentElement.disabled = true;
		s.parentElement.children[1].innerHTML = "Invalid File Format!";
	} else {
		s.disabled = false;
		s.parentElement.disabled = false;
		s.parentElement.children[1].innerHTML = "";
	}
}
