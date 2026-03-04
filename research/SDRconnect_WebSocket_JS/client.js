const wsUri = "ws://127.0.0.1:5454/";
let websocket = null;
let canvasContext = null;
let lastBins = null;

const logElement = document.querySelector("#log");

const vfoFreqElement = document.getElementById("vfo_frequency");
const vfoFreqSetElement = document.getElementById("vfo_frequency_set");
const centerFreqElement = document.getElementById("center_frequency");
const centerFreqSetElement = document.getElementById("center_frequency_set");
const canvasElement = document.getElementById("spectrum_canvas");
const demodModeElement = document.getElementById("demod_mode");
const filterBandwidthElement = document.getElementById("filter_bandwidth");
const filterBandwidthSetElement = document.getElementById("filter_bandwidth_set");

function log(text) {
	logElement.innerText = `${logElement.innerText}${text}\n`;
	logElement.scrollTop = logElement.scrollHeight;
}

function initializeWebSocketListeners(ws) {
	ws.addEventListener("open", () => {
		log("Connected");
		
		requestPropertyValue("device_vfo_frequency");
		requestPropertyValue("device_center_frequency");
		requestPropertyValue("demodulator");
		requestPropertyValue("filter_bandwidth");
		
		vfoFreqSetElement.addEventListener("click", setVfoFrequency);
		centerFreqSetElement.addEventListener("click", setCenterFrequency);
		filterBandwidthSetElement.addEventListener("click", setFilterBandwidth);
		demodModeElement.addEventListener("change", setDemod);
		enableSpectrumStreaming();
		window.requestAnimationFrame(renderSpectrum);
	});

	ws.addEventListener("close", () => {
		log("Disconnected");		
	});

	ws.addEventListener("message", (e) => {	
		if(typeof e.data == "string") {
			parseTextMessage(e.data);
		}
		else
		{			
			parseBinaryMessage(e.data);
		}
	});

	ws.addEventListener("error", (e) => {
		log(`ERROR`);
	});
}

function parseTextMessage(message) {
	
	var m = JSON.parse(message);
	log(`event_type: ${m.event_type} property: ${m.property} value: ${m.value}`);
	
	if(m.event_type == "property_changed" || m.event_type == "get_property_response") {
		
		if(m.property == "device_vfo_frequency") {
			vfoFreqElement.value = m.value;
		}
		else 
		if(m.property == "device_center_frequency") {
			centerFreqElement.value = m.value;
		}
		else
		if(m.property == "demodulator") {
			demodModeElement.value = m.value;
		}
		else
		if(m.property == "filter_bandwidth") {
			filterBandwidthElement.value = m.value;
		}
		
	}
}

function parseBinaryMessage(message) {
	const int16Array = new Int16Array(message);
		
	if(int16Array[0] == 0x0003)
	{
		lastBins = new Uint8Array(message);	
	}
}

function renderSpectrum() {

	if(lastBins == null) {
		window.requestAnimationFrame(renderSpectrum);
		return;
	}
	
	if(canvasContext == null) {
		canvasContext = canvasElement.getContext("2d");
	}
	
	canvasContext.reset();
	
	canvasContext.save();
	canvasContext.moveTo(0, canvasElement.height);
	
	var verticalScale = canvasElement.height / 255.0;
	for(var i = 0 ; i < lastBins.length; i++)
	{
		canvasContext.lineTo(i, canvasElement.height - (lastBins[i] * verticalScale));
		
	}
	canvasContext.stroke();
	canvasContext.restore();
	
	window.requestAnimationFrame(renderSpectrum);
}

function requestPropertyValue(property) {
	var obj = {event_type: "get_property", property: property };
	var m = JSON.stringify(obj);
	websocket.send(m);
}

function setVfoFrequency() {
	var obj = {event_type: "set_property", property: "device_vfo_frequency", value: vfoFreqElement.value };
	var m = JSON.stringify(obj);
	websocket.send(m);
}

function setCenterFrequency() {
	var obj = {event_type: "set_property", property: "device_center_frequency", value: centerFreqElement.value };
	var m = JSON.stringify(obj);
	websocket.send(m);
}

function enableSpectrumStreaming() {

	var obj = {event_type: "spectrum_enable", value: "true"};
	var m = JSON.stringify(obj);
	websocket.send(m);
}

function disableSpectrumStreaming() {

	var obj = {event_type: "spectrum_enable", value: "false"};
	var m = JSON.stringify(obj);
	websocket.send(m);
}

function setDemod() {
	var obj = {event_type: "set_property", property: "demodulator", value: demodModeElement.value};
	var m = JSON.stringify(obj);
	websocket.send(m);
}

function setFilterBandwidth() {
	var obj = {event_type: "set_property", property: "filter_bandwidth", value: filterBandwidthElement.value};
	var m = JSON.stringify(obj);
	websocket.send(m);
}

window.addEventListener("pageshow", (event) => {
	if (event.persisted) {
		websocket = new WebSocket(wsUri);
		initializeWebSocketListeners(websocket);
	}
});

log("Opening...");
websocket = new WebSocket(wsUri);
websocket.binaryType = 'arraybuffer';
initializeWebSocketListeners(websocket);

window.addEventListener("pagehide", () => {
	if (websocket) {
		log("Closing");
		websocket.close();
		websocket = null;		
	}
});
