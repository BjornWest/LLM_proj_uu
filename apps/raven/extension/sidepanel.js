const port = new URLSearchParams(location.search).get('port') || '8766';
document.querySelector('iframe').src = 'http://127.0.0.1:'+port+'/panel.html';
