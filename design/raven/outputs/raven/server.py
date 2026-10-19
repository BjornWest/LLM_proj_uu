"""Local raven site and public-page preview endpoint (Python standard library).

Run: python work/server_v33.py --port 8765
Only loopback clients/hosts are served. Upstream requests resolve and pin public
IP addresses; every redirect and image gets the same validation. No credentials,
cookies, forwarded headers, browser screenshots, or third-party proxy are used.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor,TimeoutError as FutureTimeout
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,urljoin,parse_qs
import argparse,html,http.client,ipaddress,json,re,socket,ssl,threading,time,zlib

SCRIPT=Path(__file__).resolve()
DEFAULT_DIRECTORY=SCRIPT.parent.parent/'outputs'/'raven' if SCRIPT.parent.name=='work' else SCRIPT.parent
TOTAL_TIMEOUT=6.0; MAX_HTML=512*1024; MAX_IMAGE=2*1024*1024
MAX_REDIRECTS=3; CACHE_TTL=3600; ERROR_TTL=120
DNS_POOL=ThreadPoolExecutor(max_workers=4,thread_name_prefix='preview-dns')
DNS_SLOTS=threading.BoundedSemaphore(4); FETCH_SLOTS=threading.BoundedSemaphore(6)
SSL_CONTEXT=ssl.create_default_context()
TRANSITIONAL_V6=[ipaddress.ip_network(n) for n in ['64:ff9b::/96','64:ff9b:1::/48','2002::/16','2001::/32']]
IMAGE_TYPES={'image/png','image/jpeg','image/gif','image/webp','image/x-icon','image/vnd.microsoft.icon'}

class PreviewError(Exception): pass

def normalized_url(value):
    if not isinstance(value,str) or len(value)>2048 or re.search(r'[\x00-\x20\x7f\\]',value):
        raise PreviewError('Invalid website URL')
    try:
        p=urlsplit(value)
        if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password:
            raise PreviewError('Only public HTTP and HTTPS websites are supported')
        host=p.hostname.rstrip('.').encode('idna').decode('ascii').lower()
        if '%' in host or (':' not in host and not re.fullmatch(r'[a-z0-9.-]+',host)):
            raise PreviewError('Invalid website host')
        if host=='localhost' or host.endswith(('.localhost','.local','.internal','.home','.lan','.onion','.test','.invalid')):
            raise PreviewError('Local/private hosts are not previewed')
        port=p.port or (443 if p.scheme=='https' else 80)
        if port!=(443 if p.scheme=='https' else 80): raise PreviewError('Nonstandard website port')
        netloc='['+host+']' if ':' in host else host
        return urlunsplit((p.scheme,netloc,p.path or '/',p.query,''))
    except (ValueError,UnicodeError) as exc: raise PreviewError('Invalid website URL') from exc

def is_public_ip(value):
    try: address=ipaddress.ip_address(value.split('%')[0])
    except ValueError:return False
    if '%' in value or not address.is_global or address.is_multicast or address.is_reserved:return False
    if isinstance(address,ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:return is_public_ip(str(address.ipv4_mapped))
        if any(address in network for network in TRANSITIONAL_V6):return False
    return True

def public_addresses(host,port,deadline):
    if not DNS_SLOTS.acquire(blocking=False):raise PreviewError('Preview service is busy')
    future=DNS_POOL.submit(socket.getaddrinfo,host,port,0,socket.SOCK_STREAM)
    future.add_done_callback(lambda _:DNS_SLOTS.release())
    try:addresses=future.result(timeout=max(.05,min(1.5,deadline-time.monotonic())))
    except (FutureTimeout,OSError) as exc:raise PreviewError('Website lookup unavailable') from exc
    if not addresses or any(not is_public_ip(item[4][0]) for item in addresses):
        raise PreviewError('Local/private addresses are not previewed')
    return sorted(addresses,key=lambda item:item[0]!=socket.AF_INET)

def pinned_socket(host,port,tls,deadline):
    addresses=public_addresses(host,port,deadline); last=None
    for family,kind,protocol,_,address in addresses:
        sock=socket.socket(family,kind,protocol)
        try:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Preview timed out')
            sock.settimeout(min(1.5,remaining));sock.connect(address)
            if tls:sock=SSL_CONTEXT.wrap_socket(sock,server_hostname=host)
            return sock
        except (OSError,ssl.SSLError) as exc:last=exc;sock.close()
    raise PreviewError('Website connection unavailable') from last

def fetch_public(value,kind='html'):
    url=normalized_url(value);deadline=time.monotonic()+TOTAL_TIMEOUT
    for redirect in range(MAX_REDIRECTS+1):
        p=urlsplit(url);host=p.hostname;port=443 if p.scheme=='https' else 80
        connection=http.client.HTTPConnection(host,port,timeout=TOTAL_TIMEOUT)
        connection.connect=lambda:setattr(connection,'sock',pinned_socket(host,port,p.scheme=='https',deadline))
        try:
            path=p.path+('?' + p.query if p.query else '')
            connection.request('GET',path,headers={'Host':p.netloc,'User-Agent':'RavenChatPreview/33',
                'Accept':'text/html,application/xhtml+xml' if kind=='html' else 'image/png,image/jpeg,image/webp,image/gif,image/x-icon',
                'Accept-Encoding':'identity','Connection':'close'})
            response=connection.getresponse()
            if response.status in {301,302,303,307,308}:
                location=response.getheader('Location')
                if not location or redirect==MAX_REDIRECTS:raise PreviewError('Website redirect unavailable')
                url=normalized_url(urljoin(url,location));continue
            if response.status!=200:raise PreviewError('Website declined its preview')
            content_type=response.getheader('Content-Type','').split(';')[0].strip().lower()
            if kind=='html' and content_type not in {'text/html','application/xhtml+xml'}:raise PreviewError('Website is not an HTML page')
            if kind=='image' and content_type not in IMAGE_TYPES:raise PreviewError('Preview image type unavailable')
            limit=MAX_HTML if kind=='html' else MAX_IMAGE
            length=response.getheader('Content-Length','')
            if kind=='image' and length.isdigit() and int(length)>limit:raise PreviewError('Preview image too large')
            encoding=response.getheader('Content-Encoding','identity').strip().lower()
            if encoding not in {'','identity','gzip','deflate'}:raise PreviewError('Website encoding unavailable')
            decoder=zlib.decompressobj(16+zlib.MAX_WBITS if encoding=='gzip' else zlib.MAX_WBITS) if encoding in {'gzip','deflate'} else None
            payload=bytearray();encoded=0
            while len(payload)<limit:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise PreviewError('Website preview timed out')
                connection.sock.settimeout(min(1.5,remaining)) if connection.sock else None
                block=response.read1(min(16384,limit-len(payload)))
                if not block:break
                encoded+=len(block)
                if encoded>limit:raise PreviewError('Website response too large')
                output=decoder.decompress(block,limit-len(payload)+1) if decoder else block
                payload.extend(output)
                if len(payload)>limit:raise PreviewError('Website response too large')
                if kind=='html' and b'</head' in payload.lower():break
            if kind=='image' and (len(payload)==limit and response.read1(1)):raise PreviewError('Preview image too large')
            charset='utf-8';match=re.search(r'charset\s*=\s*[\"\x27]?([A-Za-z0-9._-]+)',response.getheader('Content-Type',''),re.I)
            if match:charset=match.group(1)
            return {'url':url,'body':bytes(payload),'contentType':content_type,'charset':charset}
        except PreviewError:raise
        except (OSError,ValueError,http.client.HTTPException,zlib.error) as exc:raise PreviewError('Website preview unavailable') from exc
        finally:connection.close()
    raise PreviewError('Website redirect unavailable')

def clean_text(value,limit):
    return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>','',value or ''))).strip()[:limit]

class MetadataParser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.meta={};self.title=[];self.in_title=False;self.icon=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='title':self.in_title=True
        if tag=='meta':
            key=(a.get('property') or a.get('name') or '').lower()
            if key and a.get('content') and key not in self.meta:self.meta[key]=a['content']
        if tag=='link' and not self.icon and 'icon' in (a.get('rel') or '').lower().split() and a.get('href'):self.icon=a['href']
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
    def handle_data(self,text):
        if self.in_title:self.title.append(text)

def public_asset_url(value,base):
    try:return normalized_url(urljoin(base,value)) if value else None
    except PreviewError:return None

def metadata_for(value):
    document=fetch_public(value);parser=MetadataParser()
    try:text=document['body'].decode(document['charset'],errors='replace')
    except LookupError:text=document['body'].decode('utf-8',errors='replace')
    parser.feed(text);meta=parser.meta;url=document['url'];host=urlsplit(url).hostname
    title=clean_text(meta.get('og:title') or meta.get('twitter:title') or ''.join(parser.title) or host,180)
    return {'url':url,'title':title,'description':clean_text(meta.get('og:description') or meta.get('twitter:description') or meta.get('description'),420),
            'siteName':clean_text(meta.get('og:site_name') or host,100),
            'image':public_asset_url(meta.get('og:image') or meta.get('twitter:image') or meta.get('twitter:image:src'),url),
            'favicon':public_asset_url(parser.icon or '/favicon.ico',url),'status':'ok'}

def valid_image(data,content_type):
    # No SVG/HTML image responses. Keep compressed bytes and decoded dimensions bounded.
    width=height=None
    if content_type=='image/png' and data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=24:
        width=int.from_bytes(data[16:20],'big');height=int.from_bytes(data[20:24],'big')
    elif content_type=='image/gif' and data[:6] in {b'GIF87a',b'GIF89a'} and len(data)>=10:
        width=int.from_bytes(data[6:8],'little');height=int.from_bytes(data[8:10],'little')
    elif content_type=='image/jpeg' and data.startswith(b'\xff\xd8'):
        index=2
        while index+4<len(data):
            if data[index]!=255:index+=1;continue
            marker=data[index+1];index+=2
            if marker in {0,255,216,217} or 208<=marker<=215:continue
            length=int.from_bytes(data[index:index+2],'big')
            if length<2:break
            if marker in {192,193,194,195,197,198,199,201,202,203,205,206,207} and index+7<len(data):
                height=int.from_bytes(data[index+3:index+5],'big');width=int.from_bytes(data[index+5:index+7],'big');break
            index+=length
    elif content_type=='image/webp' and data[:4]==b'RIFF' and data[8:12]==b'WEBP':
        if data[12:16]==b'VP8X' and len(data)>=30:
            width=1+int.from_bytes(data[24:27],'little');height=1+int.from_bytes(data[27:30],'little')
        elif data[12:16]==b'VP8 ':
            signature=data.find(b'\x9d\x01\x2a',20,40)
            if signature!=-1 and len(data)>=signature+7:
                width=int.from_bytes(data[signature+3:signature+5],'little')&0x3fff;height=int.from_bytes(data[signature+5:signature+7],'little')&0x3fff
        elif data[12:16]==b'VP8L' and len(data)>=25 and data[20]==47:
            bits=int.from_bytes(data[21:25],'little');width=1+(bits&0x3fff);height=1+((bits>>14)&0x3fff)
    elif content_type in {'image/x-icon','image/vnd.microsoft.icon'} and data[:4]==b'\x00\x00\x01\x00' and len(data)>=22:
        width=data[6] or 256;height=data[7] or 256
    return bool(width and height and width<=4096 and height<=4096 and width*height<=12_000_000)

class BoundedCache:
    def __init__(self,max_items=256,max_bytes=24*1024*1024):self.items=OrderedDict();self.lock=threading.Lock();self.max_items=max_items;self.max_bytes=max_bytes;self.bytes=0
    def get(self,key):
        with self.lock:
            row=self.items.get(key)
            if not row:return None
            if row[0]<time.monotonic():self.bytes-=row[2];del self.items[key];return None
            self.items.move_to_end(key);return row[1]
    def put(self,key,value,ttl=CACHE_TTL):
        size=len(value['body']) if isinstance(value,dict) and 'body' in value else len(json.dumps(value).encode())
        with self.lock:
            if key in self.items:self.bytes-=self.items.pop(key)[2]
            self.items[key]=(time.monotonic()+ttl,value,size);self.bytes+=size
            while len(self.items)>self.max_items or self.bytes>self.max_bytes:
                _,row=self.items.popitem(last=False);self.bytes-=row[2]

CACHE=BoundedCache()

def preview(value):
    try:url=normalized_url(value)
    except PreviewError:return {'url':'','title':'Website','description':'','siteName':'','image':None,'favicon':None,'status':'unavailable'}
    key=('html',url);cached=CACHE.get(key)
    if cached:return cached
    if not FETCH_SLOTS.acquire(blocking=False):return {'url':url,'title':urlsplit(url).hostname,'status':'unavailable'}
    try:
        try:result=metadata_for(url)
        except PreviewError:result={'url':url,'title':urlsplit(url).hostname,'description':'','siteName':urlsplit(url).hostname,'image':None,'favicon':None,'status':'unavailable'}
        CACHE.put(key,result,CACHE_TTL if result['status']=='ok' else ERROR_TTL);return result
    finally:FETCH_SLOTS.release()

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):self.send_header('X-Content-Type-Options','nosniff');super().end_headers()
    def allowed_client(self):
        try:host=urlsplit('//'+self.headers.get('Host','')).hostname
        except ValueError:return False
        if host not in {'localhost','127.0.0.1','::1'}:return False
        origin=self.headers.get('Origin')
        if origin:
            try:p=urlsplit(origin)
            except ValueError:return False
            if p.scheme!='http' or p.hostname!=host or p.port!=self.server.server_port:return False
        return True
    def do_GET(self):
        if not self.allowed_client():self.send_error(403,'Local origin required');return
        path=urlsplit(self.path)
        if path.path not in {'/api/link-preview','/api/link-preview-image'}:super().do_GET();return
        value=parse_qs(path.query).get('url',[''])[0]
        if path.path=='/api/link-preview':
            body=json.dumps(preview(value),ensure_ascii=False).encode('utf-8');self.send_response(200)
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','private, max-age=120')
        else:
            try:
                url=normalized_url(value);key=('image',url);asset=CACHE.get(key)
                if not asset:
                    if not FETCH_SLOTS.acquire(blocking=False):raise PreviewError('Preview service busy')
                    try:
                        asset=fetch_public(url,'image')
                        if not valid_image(asset['body'],asset['contentType']):raise PreviewError('Preview image unavailable')
                        CACHE.put(key,asset)
                    finally:FETCH_SLOTS.release()
                body=asset['body'];self.send_response(200);self.send_header('Content-Type',asset['contentType'])
                self.send_header('Cache-Control','private, max-age=3600');self.send_header('Content-Security-Policy',"default-src 'none'; sandbox")
            except PreviewError:self.send_error(404,'Preview image unavailable');return
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_HEAD(self):
        if not self.allowed_client():self.send_error(403,'Local origin required');return
        if urlsplit(self.path).path.startswith('/api/'):self.send_error(405,'GET required');return
        super().do_HEAD()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);parser.add_argument('--directory',type=Path,default=DEFAULT_DIRECTORY)
    args=parser.parse_args();directory=args.directory.resolve();assert directory.is_dir()
    handler=lambda *a,**kw:Handler(*a,directory=str(directory),**kw)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler);server.daemon_threads=True
    print(f'Raven preview server: http://127.0.0.1:{args.port}/ (public website previews enabled)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();DNS_POOL.shutdown(wait=False,cancel_futures=True)

if __name__=='__main__':main()
