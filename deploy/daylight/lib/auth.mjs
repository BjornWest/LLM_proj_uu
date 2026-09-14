import {createHash, createHmac, timingSafeEqual} from 'node:crypto';

export const digest = value => createHash('sha256').update(value).digest('hex');
const equal = (a,b) => typeof a === 'string' && typeof b === 'string' &&
  a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));
export function config(env=process.env) {
  if (!env.DEMO_SESSION_SECRET || env.DEMO_SESSION_SECRET.length < 43) throw Error('Access is not configured');
  const invites=JSON.parse(env.DEMO_INVITES_JSON || '{}');
  if (!Object.keys(invites).length || Object.entries(invites).some(([id,hash])=>
    !/^[a-z0-9-]{1,40}$/.test(id) || !/^[a-f0-9]{64}$/.test(hash))) throw Error('Invalid invitations');
  return {secret:env.DEMO_SESSION_SECRET, invites};
}
const signature = (body,secret) => createHmac('sha256',secret).update(body).digest('base64url');
export function login(code,settings,now=Date.now()) {
  if (typeof code !== 'string' || code.length < 32 || code.length > 200) return null;
  const hash=digest(code);
  const id=Object.keys(settings.invites).find(id=>equal(settings.invites[id],hash));
  if (!id) return null;
  const body=Buffer.from(JSON.stringify({id,hash,expires:now+7*86400000})).toString('base64url');
  return body+'.'+signature(body,settings.secret);
}
export function authenticate(cookie,settings,now=Date.now()) {
  try {
    const token=(cookie||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('daylight_session='))?.slice(17);
    if (!token || token.length>1024) return null;
    const [body,sig,...extra]=token.split('.');
    if (extra.length || !equal(sig,signature(body,settings.secret))) return null;
    const data=JSON.parse(Buffer.from(body,'base64url'));
    return data.expires>now && equal(settings.invites[data.id],data.hash) ? data.id : null;
  } catch {return null;}
}
export function sessionCookie(value,local=false) {
  return `daylight_session=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${value?604800:0}${local?'':'; Secure'}`;
}
