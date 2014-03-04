from __future__ import division
import serial
import time
from collections import deque
import sys


class packet(object):
  def __init__(self, dest, src, cmd, data):
    self.dest=dest
    self.src=src
    self.cmd=cmd
    self.data=data

  def __hash__(self):
    return hash(repr(self))

  def __eq__(self, other):
    return repr(self)==repr(other)

  def __repr__(self):
    return "mrbus.packet(0x%02x, 0x%02x, 0x%02x, %s)"%(self.dest, self.src, self.cmd, repr(self.data))

  def __str__(self):
    c='(%02xh'%self.cmd
    if self.cmd >= 32 and self.cmd <= 127:
      c+=" '%c')"%self.cmd
    else:
      c+="    )"
    return "packet(%02xh->%02xh) %s %2d:%s"%(self.src, self.dest, c, len(self.data), ["%02xh"%d for d in self.data])

class node(object):
  class CMP(object):
    def _startTimerHandler(self):
      if not self._supportsCMP:
        self.node.sendpkt([0xff, 0x00])#CMP capabilites request
        self.node.log(0, 'trying cmt start')
        self._tryStartHint = self.node.installTimer(self._tryStartDelay, lambda: self._startTimerHandler()) 
        self._tryStartDelay = min(10, self._tryStartDelay*1.5)



    def __init__(self, node, enableCMP):
      self.node=node
      self._supportsCMP = None #unsure at start
      if not enableCMP:
        self._supportsCMP = False
      
      self._tryStartDelay = .15

      if enableCMP:
        node.install(lambda p: self._handler(p))
        self._startTimerHandler()

    def _handler(self, p):
      if p.cmd == 0xff or p.cmd == 0xfe:
        self.node.log(0, 'cmp pkt: %s'%p)
        self._supportsCMP = True
        if self._tryStartHint:
          self.node.removeTimer(self._tryStartHint)
        return True #eat packet

    def maxPktLen(self, timeout=0):
      if self._supportsCMP == False:
        return 20

      return 20
      
    def isSupported(self, timeout=0):
      #can't block for something that might NEVER return
      assert timeout != None
      if timeout == None:
        timeout = 2 

      #return answer now if we should or can
      if timeout == 0 or self._supportsCMP != None:
        return self._supportsCMP

      self.node.pump(until=lambda:self._supportsCMP, duration=timeout)

      return self._supportsCMP

  def __init__(self, mrb, addr, enableCMP=True):
    def _handler(p):
      if p.src==self.addr and (p.dest==mrb.addr or p.dest==0xff):
        for hint,h in self.handlers:
          if h(p):
            break
        return True #eat packet

    self.mrb=mrb
    self.addr=addr
    self.hint=mrb.install(_handler)

    self.handlern=0
    self.handlers=[]

    self.cmp = node.CMP(self, enableCMP)

  def __dell__(self):
    self.mrb.remove(self.hint)

  def log(self, level, msg):
    self.mrb.mrbs.log(level, ('node %02Xh:'%self.addr)+msg)

  def install(self, handler, where=-1):
    #interpret index differently than list.insert().  -1 is at end, 0 is at front
    if where<0:
      if where == -1:
        where = len(self.handlers)
      else:
        where+=1

    hint=self.handlern
    self.log(0, "install handler %d:%s"%(hint,handler))
    self.handlern+=1
    self.handlers.insert(where, (hint, handler))
    return hint

  def remove(self, hint):
    self.log(0, "remove handler %d"%hint)
    self.handlers = [h for h in self.handlers if h[0]!=hint]

  def installTimer(self, when, handler, absolute=False):
    return self.mrb.installTimer(when, handler, absolute)

  def removeTimer(self, hint):
    self.mrb.removeTimer(hint)


  def __str__(self):
    return "node(%02) %s"%(self.addr)

  def sendpkt(self, data):
    self.mrb.sendpkt(self.addr, data)

  def getfilteredpkt(self, f, duration=None, until=None):
    pkt=[None]
    def h(p):
      if f(p):
        pkt[0]=p
        return True

    def u():
      return pkt[0]!=None or until != None and until()
      
    hint = self.install(h)
    self.pump(duration, u)
    self.remove(hint)
    return pkt[0]

  def gettypefilteredpktdata(self, t, duration=None):
    if type(t) == str:
      t=ord(t)
    p=self.getfilteredpkt(lambda p: p.cmd==t, duration=duration)
    if p:
      return p.data
    return None

  def doUntilReply(self, cmd, rep=None, delay=.5, timeout=5):
    if rep==None:
      rep=ord(cmd[0].lower())
    for i in xrange(1 + int(timeout//delay)):
      self.sendpkt(cmd)
      d = self.gettypefilteredpktdata(rep, duration=delay)
      if d != None:
        return d
    return None


  def pump(self, duration=None, until=None, eager=False):
    self.mrb.pump(duration, until, eager)

  def pumpout(self):
    self.mrb.pumpout()


class mrbusSimple(object):
  def __init__(self, port, addr, logfile=None, logall=False, extra=False):

    if type(port)==str:
      port = serial.Serial(port, 115200, timeout=.1, rtscts=True)

    self.serial = port

    time.sleep(.1)
    while port.inWaiting():
      port.read(port.inWaiting())
    port.write(':CMD NS=00;\r')
    if extra:
      port.write(':CMD MM=00;\r')
    else:
      port.write(':CMD MM=01;\r')
  
    port.timeout=0

    self.pktlst=[]

    self.logfile=logfile
    self.logall=logall
    self.log(0, "instantiated mrbusSimple from %s"%port.name)

    self.addr=addr
#    self.buf=deque()

  def setTimeout(self, to):
    self.serial.timeout = to

  def time(self):
    return time.time()

  def sleep(self, t):
    time.sleep(t)


  def log(self, error, msg):
    if not self.logfile:
      return
    if not (error or self.logall):
      return
    if error:
      s="Error:"
    else:
      s="  log:"
    self.logfile.write(s+repr(msg)+'\n')

#needs timeout functionality
#  def readline(self)
#    while not self.linebuf():
#      r=self.serial.read(max(1, self.serial.inWaiting()))
#      while '\n' in r:
#        i = r.index('\n')
#        self.linebuf.append(list(self.linecbuf)+r[:i+1]        
#        self.linecbuf=deque()
#        r=r[i+1:]
#      if r:
#        self.linecbuf.extend(r)
#    return self.linebuf.leftpop()


  def getpkt(self):
    l = self.serial.readline()
#      self.readline()
    if not l:
      return None
    if l[-1] != '\n' and l[-1] != '\r':
      self.log(1, '<<<'+l)
      return False
    l2=l.strip()
    if l2 == 'Ok':
      self.log(0, '<<<'+l)
      return False
    if len(l2)<2 or l2[0]!='P' or l2[1]!=':':
      self.log(1, '<<<'+l)
      return False
    d=[int(v,16) for v in l2[2:].split()]
    if len(d)<6 or len(d)!=d[2]:
      self.log(1, '<<<'+l)
      return False
    self.log(0, '<<<'+l)
    return packet(d[0], d[1], d[5], d[6:])


  def sendpkt(self, dest, data, src=None):
    if src == None:
      src = self.addr
    s = ":%02X->%02X"%(src, dest)
    for d in data:
      if type(d) == str:
        d=ord(d)
      s+=" %02X"%(d&0xff)
    s+=";\r"
    self.log(0, '>>>'+s)
    self.serial.write(s)

class mrbus(object):
  def __init__(self, port, addr=None, logfile=None, logall=False, extra=False):

    if type(port)==str:
      port = serial.Serial(port, 115200, rtscts=True)

    if type(port)==serial.Serial:
      self.mrbs = mrbusSimple(port, addr, logfile, logall, extra)
    else:
      self.mrbs = port

    self.pktlst=[]
    self.handlern=0
    self.handlers=[]
    self.timeHandlers = []

    self.kill=False

    self.mrbs.log(0, "instantiated mrbus from %s"%port.name)

    self.pumpout()
    
    #find an address to use
    if addr==None:
      self.mrbs.log(0, "finding address to use")
      for addr in xrange(254, 0, -1):
        found = self.testnode(addr, replyto=0xff)
        if not found:
          break
      if found:
        self.mrbs.log(1, "no available address found to use")
        raise Exception("no available address found to use")
     
    self.addr=addr
    self.mrbs.addr=addr

    self.mrbs.log(0, "using address %d"%addr)


  def sendpkt(self, addr, data, src=None):
    self.mrbs.sendpkt(addr, data, src)

  def getnode(self, dest):
    return node(self, dest)

  def install(self, handler, where=-1):
    #interpret index differently than list.insert().  -1 is at end, 0 is at front
    if where<0:
      if where == -1:
        where = len(self.handlers)
      else:
        where+=1

    hint=self.handlern
    self.mrbs.log(0, "install handler %d:%s"%(hint,handler))
    self.handlern+=1
    self.handlers.insert(where, (hint, handler))
    return hint

  def remove(self, hint):
    self.mrbs.log(0, "remove handler %s"%hint)
    self.handlers = [h for h in self.handlers if h[0]!=hint]

  def installTimer(self, when, handler, absolute=False):
    if not absolute:
      when += self.mrbs.time()
    self.mrbs.log(0, "install timer for %s"%when)
    hint=self.handlern
    self.handlern+=1
    self.timeHandlers.append((when, hint, handler))
    self.timeHandlers.sort(reverse=True)
    return hint

  def removeTimer(self, hint):
    self.mrbs.log(0, "remove timer")
    self.timeHandlers = [h for h in self.timeHandlers if h[1]!=hint]

  def pump(self, duration=None, until=None, eager=False):
    start = self.mrbs.time()
    now = start
    while eager or not self.kill and (duration==None or duration+start > now) and (until==None or not until()):
      while self.timeHandlers and self.timeHandlers[-1][0] <= now:
        h = self.timeHandlers.pop()
        h[2]()
        now = self.mrbs.time()
      if self.timeHandlers:
        to = self.timeHandlers[-1][0] - now
      else:
        to = .1
      if duration != None:
        to=min(to,max(0,duration+start-now))
      self.mrbs.setTimeout(to)
      p = self.mrbs.getpkt()
      if p:
        for hint,h in self.handlers:
          if h(p):
            break
      elif p==None:
        eager=False
      now = self.mrbs.time()

  def pumpout(self):
    self.pump(duration=0, eager=True)

  def testnode(self, addr, replyto=None, wait=2):
    found=False

    def pingback(p):
      if p.src==addr:
        found=True
      if p.cmd=='a':
        return True #eat pings
      return False

    if replyto == None:
      replyto = self.addr

    hint = self.install(pingback, 0)

    t=self.mrbs.time()
    n=0
    while self.mrbs.time()-t < wait and not found:
      x=(self.mrbs.time()-t)/.2
      if x > n:
        self.sendpkt(addr, ['A'], src=replyto)
        n+=1
      tn=self.mrbs.time()
      to=min(wait+t-tn, n*.2+t-tn)
      self.pump(to)

    self.remove(hint)
    return found


        
  def scannodes(self, pkttype=ord('A'), rettype=None, wait=2):
    targets=set()

    if rettype==None:
      rettype=ord(pkttype.lower())

    def pingback(p):
      if p.src!=self.mrbs.addr and p.src!=0 and p.src!=0xff and p.cmd==rettype:
        targets.add(p)
      return False

    hint = self.install(pingback, 0)

    t=self.mrbs.time()
    n=0
    while self.mrbs.time()-t < wait:
      x=(self.mrbs.time()-t)/.3
      if x > n:
        self.sendpkt(0xff, [pkttype])
        n+=1
      tn=self.mrbs.time()
      to=min(wait+t-tn, n*.3+t-tn)
      self.pump(to)

    self.remove(hint)
    return sorted(targets)



###mrbus example use:
def mrbus_ex(ser):
  mrb = mrbus(ser)
#  mrb = mrbus(ser, logall=True, logfile=sys.stderr)
  nodes = mrb.scannodes()
  print 'nodes: '+', '.join(str(n.src) for n in nodes)


###node example use:
def node_ex(ser):
  mrb = mrbus(ser)
  nodes = mrb.scannodes()
  assert nodes

  n=mrb.getnode(nodes[0].src)

  n.pumpout()
  n.sendpkt(['V'])
  #or this: print node.getfilteredpkt(lambda p: p.cmd==ord('v'), duration=2).data
  print node.gettypefilteredpktdata('v')
  if p:
    print p
  else:
    print 'no packet returned'

  #or this: d = n.doUntilReply(['V'])


###mrbusSimple example use:
#might be out of date from event loop updates
def mrbussimple_ex(ser):
  addr=0
  mrbs = mrbusSimple(ser, addr)
#  mrbs = mrbusSimple(ser, logall=True, logfile=sys.stderr)
  t=mrbs.time()
  while mrbs.time()-t < 3:
    mrbs.sendpkt(0xff, ['A'])
    mrbs.sleep(.3)
    while 1:
      p = mrbs.getpkt()
      if p==None:
        break
      if p.src!=addr and p.src!=0 and p.src!=0xff:
        print 'recieved reply from node:', p.src


if __name__ == '__main__':
  with serial.Serial('/dev/ttyUSB0', 115200, timeout=0, rtscts=True) as ser:

#    mrbussimple_ex(ser)
#    mrbus_ex(ser)
    node_ex(ser)


