"""受限RFB 3.8/VeNCrypt显示客户端：双向TLS、Raw帧、键鼠，无剪贴板或文件传输。"""
import struct
import time
from ctflab_tls_endpoint import tcp, wrap_client

MAX_PIXELS = 4096 * 2160


class DisplayError(ValueError):
    pass


class RFBClient:
    def __init__(self, port, credentials, fingerprints, timeout=5):
        self.socket = tcp(port, timeout)
        self.timeout = timeout
        self.deadline = time.monotonic()+timeout
        self.keys = set()
        try:
            if self.read(12) != b'RFB 003.008\n':
                raise DisplayError('仅支持RFB 3.8')
            self.send(b'RFB 003.008\n')
            count = self.read(1)[0]
            if not count or 19 not in self.read(count):
                raise DisplayError('必须提供VeNCrypt；不回退无认证显示')
            self.send(b'\x13')
            if self.read(2) != b'\x00\x02':
                raise DisplayError('VeNCrypt版本不支持')
            self.send(b'\x00\x02')
            if self.read(1) != b'\x00':
                raise DisplayError('VeNCrypt版本拒绝')
            count = self.read(1)[0]
            if not 1 <= count <= 32:
                raise DisplayError('显示认证类型超限')
            subtypes = struct.unpack('>'+'I'*count, self.read(count*4))
            if 260 not in subtypes:
                raise DisplayError('必须使用X509证书；不回退匿名TLS')
            self.send(struct.pack('>I', 260))
            if self.read(1) != b'\x01':
                raise DisplayError('显示端拒绝证书协商')
            # X509None只是不另用VNC口令；服务端仍必须verify-peer=yes且匹配客户端DN。
            self.socket = wrap_client(self.socket, credentials, fingerprints)
            if self.read(4) != b'\x00'*4:
                raise DisplayError('显示认证被拒绝')
            self.send(b'\x01')  # shared：打开新客户端不踢掉其他显示连接。
            header = self.read(24)
            width, height = struct.unpack('>HH', header[:4])
            title_size = struct.unpack('>I', header[20:24])[0]
            if title_size > 4096:
                raise DisplayError('显示名称超限')
            self.read(title_size)  # 来宾/服务器名称不作为本机窗口标题或指令。
            self.resize(width, height)
            self.send(b'\x00\x00\x00\x00' + struct.pack('>BBBBHHHBBBxxx', 32,24,0,1,255,255,255,16,8,0))
            self.send(struct.pack('>BBHii', 2,0,2,0,-223))  # Raw + DesktopSize。
        except BaseException:
            self.close()
            raise

    def remaining(self):
        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('显示超时；断开连接，不影响VM')
        self.socket.settimeout(remaining)

    def read(self, size):
        if not 0 <= size <= MAX_PIXELS*4:
            raise DisplayError('显示消息超限')
        result = bytearray()
        while len(result) < size:
            self.remaining()
            raw = self.socket.recv(min(65536,size-len(result)))
            if not raw:
                raise ConnectionError('显示连接关闭')
            result.extend(raw)
        return bytes(result)

    def send(self, data):
        self.remaining()
        self.socket.sendall(data)

    def resize(self, width, height):
        if not (0 < width <= 4096 and 0 < height <= 2160 and width*height <= MAX_PIXELS):
            raise DisplayError('帧尺寸超限')
        self.width, self.height = width, height
        self.pixels = bytearray(width*height*3)

    def frame(self):
        self.deadline = time.monotonic()+self.timeout
        self.send(struct.pack('>BBHHHH',3,0,0,0,self.width,self.height))
        for _ in range(256):
            kind = self.read(1)[0]
            if kind == 2:  # Bell：不执行宿主音频操作。
                continue
            if kind == 3:
                size = struct.unpack('>I',self.read(7)[3:])[0]
                if size > 65536:
                    raise DisplayError('剪贴板消息超限')
                self.read(size)  # 直接丢弃，永不写本机剪贴板。
                continue
            if kind != 0:
                raise DisplayError('不支持的显示消息')
            count = struct.unpack('>H',self.read(3)[1:])[0]
            if count > 256:
                raise DisplayError('矩形数量超限')
            total = 0
            for _ in range(count):
                x,y,width,height,encoding = struct.unpack('>HHHHi',self.read(12))
                if encoding == -223:
                    self.resize(width,height)
                    continue
                if encoding != 0 or x+width > self.width or y+height > self.height:
                    raise DisplayError('矩形越界或编码不支持')
                total += width*height*4
                if total > MAX_PIXELS*4:
                    raise DisplayError('单次帧数据超限')
                raw = self.read(width*height*4)
                rgb = bytearray(width*height*3)
                rgb[0::3],rgb[1::3],rgb[2::3] = raw[2::4],raw[1::4],raw[0::4]
                for row in range(height):
                    offset = ((y+row)*self.width+x)*3
                    self.pixels[offset:offset+width*3] = rgb[row*width*3:(row+1)*width*3]
            return f'P6\n{self.width} {self.height}\n255\n'.encode()+self.pixels
        raise DisplayError('非帧消息过多')

    def key(self, keysym, down):
        if type(keysym) is not int or not 0 <= keysym <= 0x1fffffff or type(down) is not bool:
            raise DisplayError('按键无效')
        self.deadline = time.monotonic()+self.timeout
        self.send(struct.pack('>BBHI',4,int(down),0,keysym))
        if down:
            self.keys.add(keysym)
        else:
            self.keys.discard(keysym)

    def pointer(self,x,y,mask):
        if any(type(v) is not int for v in (x,y,mask)) or not (0 <= x < self.width and 0 <= y < self.height and 0 <= mask <= 7):
            raise DisplayError('鼠标事件无效')
        self.deadline = time.monotonic()+self.timeout
        self.send(struct.pack('>BBHH',5,mask,x,y))

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None


def show(connect):
    """connect由可信运行入口提供；每次手动重连重新核验身份与证书。"""
    import tkinter as tk
    import queue
    import threading
    root = tk.Tk()
    root.title('CTFLab 实验显示')
    status = tk.StringVar(value='正在核验并连接…')
    tk.Label(root,textvariable=status).pack()
    canvas = tk.Label(root,takefocus=True)
    canvas.pack()
    frames, inputs = queue.Queue(maxsize=1), queue.Queue(maxsize=128)
    stop = threading.Event()
    dimensions = [0,0]
    mask = [0]
    worker_running = [False]
    held = set()
    def push(value):
        try: inputs.put_nowait(value)
        except queue.Full:
            stop.set();status.set('输入队列超限，已断开；请重新连接。')
    def worker():
        client = None
        try:
            client = connect()
            while not stop.is_set():
                while True:
                    try: item = inputs.get_nowait()
                    except queue.Empty: break
                    getattr(client,item[0])(*item[1:])
                frame = client.frame()
                value = ('frame',frame,client.width,client.height)
                try: frames.get_nowait()
                except queue.Empty: pass
                frames.put_nowait(value)
                stop.wait(.2)
        except Exception as exc:
            try: frames.get_nowait()
            except queue.Empty: pass
            frames.put_nowait(('error',type(exc).__name__))
        finally:
            if client:
                try:
                    for key in tuple(client.keys): client.key(key,False)
                    client.pointer(0,0,0)
                except Exception: pass
                client.close()
            worker_running[0] = False
    def reconnect():
        if worker_running[0]: return
        stop.clear();held.clear();mask[0]=0
        while not inputs.empty(): inputs.get_nowait()
        worker_running[0] = True
        threading.Thread(target=worker,daemon=True).start()
        status.set('正在核验并连接…')
    tk.Button(root,text='重新连接显示',command=reconnect).pack()
    tk.Label(root,text='关闭此窗口仅断开显示；不会关机。剪贴板和文件传输未启用。').pack()
    def render():
        try:
            value = frames.get_nowait()
            if value[0] == 'frame':
                image = tk.PhotoImage(data=value[1],format='PPM')
                scale = max(1,(value[2]+1199)//1200,(value[3]+799)//800)
                if scale > 1: image=image.subsample(scale)
                canvas.configure(image=image);canvas.image=image
                dimensions[:] = [value[2],value[3]]
                canvas.scale=scale;status.set('已连接（Raw显示）')
            else: status.set('连接已断开：'+value[1]+'；VM状态请另行查询。')
        except queue.Empty: pass
        root.after(50,render)
    def key_event(event, down):
        code = event.keysym_num
        if down: held.add(code)
        else: held.discard(code)
        push(('key',code,down));return 'break'
    def pointer_event(event,button=None,down=False):
        if not dimensions[0]: return
        canvas.focus_set()
        if button:
            if down: mask[0] |= 1 << (button-1)
            else: mask[0] &= ~(1 << (button-1))
        scale=getattr(canvas,'scale',1)
        push(('pointer',min(dimensions[0]-1,max(0,event.x*scale)),min(dimensions[1]-1,max(0,event.y*scale)),mask[0]))
    canvas.bind('<KeyPress>',lambda e:key_event(e,True))
    canvas.bind('<KeyRelease>',lambda e:key_event(e,False))
    canvas.bind('<Motion>',pointer_event)
    for button in (1,2,3):
        canvas.bind(f'<ButtonPress-{button}>',lambda e,b=button:pointer_event(e,b,True))
        canvas.bind(f'<ButtonRelease-{button}>',lambda e,b=button:pointer_event(e,b,False))
    def release(unused=None):
        for key in tuple(held): push(('key',key,False))
        held.clear();mask[0]=0
        if dimensions[0]: push(('pointer',0,0,0))
    canvas.bind('<FocusOut>',release)
    def close():
        release();stop.set();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    reconnect();render();root.mainloop()
