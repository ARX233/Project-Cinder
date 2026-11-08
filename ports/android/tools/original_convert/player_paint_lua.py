"""Bounded non-executing Lua data parser adapted from reviewed WGPAINT1 producer."""
import re
TOKEN = re.compile(r'(?P<space>\s+)|(?P<comment>--\[\[.*?\]\]|--[^\n]*)|(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|(?P<number>-?\d+\.?\d*(?:[eE][-+]?\d+)?|-?\.\d+)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>\.\.|[{}\[\]=,;()])',re.S)


def safe_relative(p):
    if not isinstance(p,str) or not p or len(p.encode('ascii'))>=128 or '\\' in p or p.startswith('/') or any(x in ('','..','.') for x in p.split('/')) or not re.fullmatch(r'[A-Za-z0-9_./-]+',p):
        raise ValueError('invalid source-relative path')
    return p

class LuaData:
    """Bounded literal grammar, not Lua interpreter. Duplicate fields are last-wins
    as the original table constructor (some official aero_c dummy fields do this).
    No calls, indexing, operators other than string concatenation, or functions.
    """
    def __init__(self,data):
        if len(data)>1024*1024: raise ValueError('Lua size cap')
        text=data.decode('utf8','strict'); self.t=[]; pos=0
        while pos<len(text):
            m=TOKEN.match(text,pos)
            if not m: raise ValueError('unsupported Lua syntax at '+str(pos))
            if m.lastgroup not in ('space','comment'):
                self.t.append((m.lastgroup,m.group(),pos,m.end()))
                if len(self.t)>100000: raise ValueError('Lua token cap')
            pos=m.end()
        self.i=0;self.env={};self.depth=0
    def peek(self,k=0): return self.t[self.i+k][:2] if self.i+k<len(self.t) else ('','')
    def take(self,v=None):
        if self.i>=len(self.t):raise ValueError('truncated Lua')
        t=self.t[self.i];self.i+=1
        if v is not None and t[1]!=v:raise ValueError('expected '+v)
        return t
    def atom(self):
        k,v,*_=self.take()
        if k=='string':
            # Source strings are ASCII paths or UTF-8 labels; admit only Lua's
            # simple quoted escapes, without eval or Python source execution.
            def esc(m):
                c=m.group(1)
                if c not in {'n':'\n','r':'\r','t':'\t','\\':'\\','"':'"',"'":"'"}:raise ValueError('unsupported string escape')
                return {'n':'\n','r':'\r','t':'\t','\\':'\\','"':'"',"'":"'"}[c]
            return re.sub(r'\\(.)',esc,v[1:-1])
        if k=='number': return float(v) if any(c in v for c in '.eE') else int(v)
        if k=='name':
            if v in ('true','false','nil'):return {'true':True,'false':False,'nil':None}[v]
            if v not in self.env: raise ValueError('undefined Lua data name '+v)
            return self.env[v]
        if v=='(':
            a=self.expr();self.take(')');return a
        if v!='{':raise ValueError('unsupported Lua atom')
        self.depth+=1
        if self.depth>32:raise ValueError('Lua nesting cap')
        keyed={};items=[]
        while self.peek()[1]!='}':
            if self.peek()[0]=='name' and self.peek(1)[1]=='=':
                name=self.take()[1];self.take('=');keyed[name]=self.expr()
            elif self.peek()[1]=='[':
                self.take('[');name=self.expr();self.take(']');self.take('=');keyed[name]=self.expr()
            else:items.append(self.expr())
            if self.peek()[1] in (',',';'):self.take()
        self.take('}');self.depth-=1
        if keyed and items:keyed.update({i+1:x for i,x in enumerate(items)})
        return keyed if keyed or not items else items
    def expr(self):
        a=self.atom()
        while self.peek()[1]=='..':
            self.take();b=self.atom()
            if not isinstance(a,str) or not isinstance(b,str):raise ValueError('nonstring concatenation')
            a+=b
            if len(a)>4096:raise ValueError('string cap')
        return a
    def parse(self):
        while self.i<len(self.t):
            k,n,*_=self.take()
            if k!='name':raise ValueError('top-level assignment only')
            self.take('=');self.env[n]=self.expr()
            if self.peek()[1]==';':self.take()
        return self.env

