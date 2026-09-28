"""Startup-only placement of owned browser windows on the Windows desktop.

A random, temporary title identifies the exact new page's native window, including
WSLg chat windows. Never match a generic Chrome title or touch unrelated windows.
"""
import base64
import json
import uuid
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / '.local/windows-browser-layout.json'

# Powershell runs with physical-pixel coordinates, including negative monitor origins.
API = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class LayoutWindows {
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x,int y,int w,int z,uint flags);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left,Top,Right,Bottom; }
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out Rect r);
    public static Rect Bounds(IntPtr h) { Rect r; if(!GetWindowRect(h,out r)) throw new Exception("Window disappeared"); return r; }
    public static long[] Find(string marker) {
        var result=new List<long>();
        EnumWindows((h,p)=>{var title=new StringBuilder(4096);GetWindowText(h,title,4096);
            if(IsWindowVisible(h) && title.ToString().Contains(marker)) result.Add(h.ToInt64());return true;},IntPtr.Zero);
        return result.ToArray();
    }
}
'@
[void][LayoutWindows]::SetThreadDpiAwarenessContext([IntPtr](-4))
'''


def load_layout(path=DEFAULT_PATH):
    path = Path(path)
    if not path.exists():
        return None
    layout = json.loads(path.read_text())
    validate_layout(layout)
    return layout


def validate_layout(layout):
    if not isinstance(layout, dict) or not isinstance(layout.get('display'), str):
        raise ValueError('layout requires a Windows display device name')
    fraction = layout.get('browser_fraction', .7)
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not .3 <= fraction <= .8:
        raise ValueError('browser_fraction must be from 0.3 to 0.8')
    height = layout.get('height_fraction', 1.0)
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not .3 <= height <= 1:
        raise ValueError('height_fraction must be from 0.3 to 1.0')


def rectangles(area, fraction=.7, height_fraction=1.0):
    x, y, w, h = (area[key] for key in ('X', 'Y', 'Width', 'Height'))
    h = round(h * height_fraction)
    split = round(w * fraction)
    return {'browser': [x, y, split, h], 'chat': [x + split, y, w - split, h]}


def displays(powershell):
    raw = powershell(API + r'''
$result=@([System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
    @{device=$_.DeviceName; primary=$_.Primary; area=@{X=$_.WorkingArea.X;Y=$_.WorkingArea.Y;Width=$_.WorkingArea.Width;Height=$_.WorkingArea.Height}}
})
ConvertTo-Json -InputObject $result -Depth 4 -Compress
''')
    return json.loads(raw)


def place_page(page, role, layout, powershell):
    validate_layout(layout)
    if role not in ('browser', 'chat'):
        raise ValueError('unknown window role')
    marker = 'BrowserAgentLayout-' + uuid.uuid4().hex
    previous = page.evaluate('(marker) => {const old=document.title;document.title=marker;return old}', marker)
    try:
        payload = base64.b64encode(json.dumps({**layout, 'browser_fraction': layout.get('browser_fraction', .7), 'height_fraction': layout.get('height_fraction', 1.0), 'marker': marker, 'role': role}).encode()).decode()
        script = API + "\n$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "')) | ConvertFrom-Json\n" + r'''
$screen=@([System.Windows.Forms.Screen]::AllScreens | Where-Object {$_.DeviceName -eq $c.display})
if($screen.Count -ne 1) { throw 'Configured display unavailable; no window moved' }
$ids=@()
for($i=0;$i -lt 30;$i++) {
    $ids=@([LayoutWindows]::Find($c.marker))
    if($ids.Count -gt 0) {break}
    Start-Sleep -Milliseconds 100
}
if($ids.Count -ne 1) {throw 'Unique owned window not found; no window moved'}
$a=$screen[0].WorkingArea
$split=[int][Math]::Round($a.Width * $c.browser_fraction)
$height=[int][Math]::Round($a.Height * $c.height_fraction)
$x=$a.X; $width=$split
if($c.role -eq 'chat') {$x+=$split; $width=$a.Width-$split}
$h=[IntPtr]$ids[0]
[void][LayoutWindows]::ShowWindow($h,4)
if(-not [LayoutWindows]::SetWindowPos($h,[IntPtr]::Zero,$x,$a.Y,$width,$height,20)) {throw 'SetWindowPos failed'}
Start-Sleep -Milliseconds 150
$r=[LayoutWindows]::Bounds($h)
@{role=$c.role;placed=$true;hwnd=$h.ToInt64();device=$c.display;requested=@($x,$a.Y,$width,$height);actual=@($r.Left,$r.Top,($r.Right-$r.Left),($r.Bottom-$r.Top))} | ConvertTo-Json -Compress
'''
        return json.loads(powershell(script))
    finally:
        if not page.is_closed():
            page.evaluate('({marker,previous}) => {if(document.title===marker) document.title=previous}',
                          {'marker': marker, 'previous': previous})
