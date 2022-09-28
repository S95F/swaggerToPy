

var path = require('path');
var express = require('express');
var serveStatic = require('serve-static');
var app = express();



const http = require('http');
const server = http.createServer(app);

const { Server } = require("socket.io");
const io = new Server(server);


var htmlPath = path.join(__dirname, 'html');
console.log(htmlPath)

io.on('connection', (socket) => {
  console.log('a user connected');
});


app.use(serveStatic(htmlPath))
server.listen(2323)
