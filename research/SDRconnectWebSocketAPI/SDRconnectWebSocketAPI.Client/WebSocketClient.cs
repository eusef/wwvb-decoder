using System.Net.WebSockets;

namespace SDRconnectWebSocketAPI.Client
{    
    public class WebSocketClient
    {
        private const int ReceiveBufferSize = 65536;

        public class WebSocketMessage
        {
            public ArraySegment<byte> Data { get; set; }
            public WebSocketMessageType Type { get; set; }

        }

        private ClientWebSocket? _ws;
        private readonly string _host;
        private readonly ushort _port;
        private readonly Uri _uri;        
        private readonly CancellationTokenSource _tokenSource;
        private readonly CancellationToken _token;
        private readonly object _writeLock = new object();

        public delegate void OnConnectedDelegate();
        public delegate void OnDisconnectedDelegate();
        public delegate void OnMessageReceivedDelegate(WebSocketMessage message);
        public event OnConnectedDelegate? OnConnected;
        public event OnDisconnectedDelegate? OnDisconnected;
        public event OnMessageReceivedDelegate? OnMessageReceived;


        public WebSocketClient(string host, ushort port)
        {
            _host = host;
            _port = port;
            _uri = new Uri(string.Format("ws://{0}:{1}", _host, _port));
            _tokenSource = new CancellationTokenSource();
            _token = _tokenSource.Token;
        }
                
        public void Start()
        {
            _ws = new ClientWebSocket();
            _ws.ConnectAsync(_uri, _token).ContinueWith(PostConnect).Wait();
        }

        public void Stop()
        {
            if (_ws != null)
            {
                _ws.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, null, _token).Wait();
            }
        }

        public void Send(string data)
        {
            lock (_writeLock)
            {
                if (_ws != null && _ws.State == WebSocketState.Open)
                {
                    _ws.SendAsync(new ArraySegment<byte>(System.Text.Encoding.UTF8.GetBytes(data)), WebSocketMessageType.Text, true, _token).Wait();
                }
            }
        }
        
        private void PostConnect(Task task)
        {         
            if(task.IsFaulted)
            {
                throw task.Exception;
            }

            if(!task.IsFaulted && task.IsCompleted)
            {
                if(_ws.State == WebSocketState.Open)
                {
                    Task.Run(() =>
                    {
                        Task.Run(() => ReceiveLoop(), _token);
                        if(OnConnected != null)
                        {
                            OnConnected();
                        }
                    }, _token);
                }
            }
        }

        private async Task ReceiveLoop()
        {               
            var buffer = new byte[ReceiveBufferSize];
                        
            try
            {
                while(true)
                {
                    if(_token.IsCancellationRequested)
                    {
                        break;
                    }

                    var m = await ReadMessage(buffer);
                    if(m != null && m.Type != WebSocketMessageType.Close)
                    {
                        if(OnMessageReceived != null)
                        {
                            OnMessageReceived(m);
                        }
                    }

                }
            }
            catch
            { 
            }

            if(OnDisconnected != null)
            {
                OnDisconnected();
            }

        }

        private async Task<WebSocketMessage?> ReadMessage(byte[] buffer)
        {
            if(_ws.State == WebSocketState.Closed || _ws.State == WebSocketState.CloseReceived)
            {
                throw new WebSocketException("Invalid websocket state");
            }
                        
            ArraySegment<byte> seg = new ArraySegment<byte>(buffer);
            ArraySegment<byte> output = null;
            WebSocketReceiveResult? result = null;

            var ms = new MemoryStream();
            while (_ws.State == WebSocketState.Open)
            {
                result = await _ws.ReceiveAsync(seg, _token);
                if (result.Count > 0)
                {
                    await ms.WriteAsync(buffer, 0, result.Count);
                }

                if (result.EndOfMessage)
                {
                    output = new ArraySegment<byte>(ms.GetBuffer(), 0, (int)ms.Length);
                    break;
                }
            }

            if (result != null)
            {
                var ret = new WebSocketMessage();
                ret.Data = output;
                ret.Type = result.MessageType;
                return ret;
            }

            return null;
        }                        
    }
}
