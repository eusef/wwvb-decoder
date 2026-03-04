
using System.Text;
using System.Net.WebSockets;

namespace SDRconnectWebSocketAPI.Client
{
    public class SDRconnectWebSocketClient
    {
        private readonly WebSocketClient _client;

        public delegate void OnConnectedDelegate();
        public delegate void OnDisconnectedDelegate();
        public delegate void OnPropertyChangedDelegate(SDRconnectProperty property, string value);
        public delegate void OnAudioReceivedDelegate(short[] audio);
        public delegate void OnIqReceivedDelegate(short[] iq);
        public delegate void OnSpectrumReceivedDelegate(byte[] spectrum);

        public event OnConnectedDelegate? OnConnected;
        public event OnDisconnectedDelegate? OnDisconnected;
        public event OnPropertyChangedDelegate? OnPropertyChanged;

        public event OnAudioReceivedDelegate? OnAudioReceived;
        public event OnIqReceivedDelegate? OnIqReceived;
        public event OnSpectrumReceivedDelegate? OnSpectrumReceived;
        
        private readonly string _host;
        private readonly ushort _port;

        private bool _audioStreamEnabled;
        private bool _iqStreamEnabled;
        private bool _spectrumStreamEnabled;
        private bool _deviceStreamEnabled;

        public string Host
        {
            get => _host;
        }

        public ushort Port
        {
            get => _port;
        }

        public bool DeviceStreamEnabled
        {
            get => _deviceStreamEnabled;
            set
            {
                _deviceStreamEnabled = value;                
                SetDeviceStreamEnable(value);                
            }
        }

        public bool AudioStreamEnabled
        {
            get => _audioStreamEnabled;
            set
            {                                
                _audioStreamEnabled = value;
                SetAudioStreamEnable(_audioStreamEnabled);                
            }
        }

        public bool IqStreamEnabled
        {
            get => _iqStreamEnabled;
            set
            {
                _iqStreamEnabled = value;
                SetIqStreamEnable(_iqStreamEnabled);                
            }
        }

        public bool SpectrumStreamEnabled
        {
            get => _spectrumStreamEnabled;
            set
            {
                if(_spectrumStreamEnabled != value)
                {
                    _spectrumStreamEnabled = value;
                    SetSpectrumEnable(_spectrumStreamEnabled);
                }
            }
        }

        public SDRconnectWebSocketClient(string host, ushort port = 5454)
        {
            _host = host;
            _port = port;

            _client = new WebSocketClient(host, port);
            _client.OnConnected += Client_OnConnected;
            _client.OnDisconnected += Client_OnDisconnected;
            _client.OnMessageReceived += Client_OnMessageReceived;
        }

        public void Start()
        {
            _client.Start();
        }

        public void Stop()
        {
            _client.Stop();
        }

        public void SetProperty(SDRconnectProperty property, string value)
        {
            var m = new SDRconnectWebSocketMessage();
            
            m.Property = property.ToString();
            m.Value = value;
            m.Type = SDRconnectWebSocketMessage.MessageType.SetPropertyRequest;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        public void GetProperty(SDRconnectProperty property)
        {
            var m = new SDRconnectWebSocketMessage();
           
            m.Property = property.ToString();
            m.Type = SDRconnectWebSocketMessage.MessageType.GetPropertyRequest;
            
            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        public void SetCurrentDevice(int deviceIndex)
        {

            var m = new SDRconnectWebSocketMessage();

            m.Value = deviceIndex.ToString();
            m.Type = SDRconnectWebSocketMessage.MessageType.SelectedDeviceIndex;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        public void SetCurrentDeviceSerial(string serialNumber)
        {
            var m = new SDRconnectWebSocketMessage();

            m.Value = serialNumber;
            m.Type = SDRconnectWebSocketMessage.MessageType.SelectedDeviceSerial;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        public void SetCurrentDeviceName(string name)
        {
            var m = new SDRconnectWebSocketMessage();

            m.Value = name;
            m.Type = SDRconnectWebSocketMessage.MessageType.SelectedDeviceName;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        public void ApplyDeviceProfile(string deviceProfile)
        {
            var m = new SDRconnectWebSocketMessage();

            m.Value = deviceProfile;
            m.Type = SDRconnectWebSocketMessage.MessageType.ApplyDeviceProfile;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        public void StartRecording(SDRconnectRecording.RecordingType recordingType)
        {
            var m = new SDRconnectWebSocketMessage();

            m.Value = recordingType.ToString();
            m.Type = SDRconnectWebSocketMessage.MessageType.StartRecording;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        public void StopRecording()
        {
            var m = new SDRconnectWebSocketMessage();
            m.Type = SDRconnectWebSocketMessage.MessageType.StopRecording;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        #region Private Functions

        private void Client_OnMessageReceived(WebSocketClient.WebSocketMessage message)
        {
            if (message.Data.Count > 0)
            {
                if (message.Type == WebSocketMessageType.Text)
                {
                    var s = Encoding.UTF8.GetString(message.Data);
                    var m = SDRconnectWebSocketMessage.FromJson(s, out var valid);
                    if (valid)
                    {
                        ProcessTextMessage(m);
                    }

                }
                else
                if (message.Type == WebSocketMessageType.Binary)
                {
                    var header = new ushort[1];
                    
                    Buffer.BlockCopy(message.Data.Array, 0, header, 0, 2);
                    
                    switch(header[0])
                    {
                        case 0x0001:
                        {
                            if (OnAudioReceived != null)
                            {
                                var audio = new short[(message.Data.Count - 2) / 2];
                                Buffer.BlockCopy(message.Data.Array, 2, audio, 0, audio.Length * 2);

                                OnAudioReceived(audio);
                            }
                        }
                        break;

                        case 0x0002:
                        {
                            if (OnIqReceived != null)
                            {
                                var iq = new short[(message.Data.Count - 2) / 2];
                                Buffer.BlockCopy(message.Data.Array, 2, iq, 0, iq.Length * 2);

                                OnIqReceived(iq);
                            }
                        }
                        break;

                        case 0x0003:
                        {
                            if (OnSpectrumReceived != null)
                            {
                                var spectrum = new byte[message.Data.Count - 2];
                                Buffer.BlockCopy(message.Data.Array, 2, spectrum, 0, spectrum.Length);

                                OnSpectrumReceived(spectrum);
                            }
                        }
                        break;        
                    }
                }
            }
            
        }

        private void Client_OnDisconnected()
        {
            if(OnDisconnected != null)
            {
                OnDisconnected();
            }
        }

        private void Client_OnConnected()
        {
            
            if (_audioStreamEnabled)
            {
                SetAudioStreamEnable(_spectrumStreamEnabled);
            }
            
            if (_iqStreamEnabled)
            {
                SetIqStreamEnable(_iqStreamEnabled);
            }

            if (_spectrumStreamEnabled)
            {
                SetSpectrumEnable(_spectrumStreamEnabled);
            }

            if (OnConnected != null)
            {
                OnConnected();
            }

        }

        private void ProcessTextMessage(SDRconnectWebSocketMessage message)
        {
            if (message.Type == SDRconnectWebSocketMessage.MessageType.PropertyChanged ||
                message.Type == SDRconnectWebSocketMessage.MessageType.GetPropertyResponse)
            {
                if (Enum.TryParse(message.Property, false, out SDRconnectProperty property))
                {
                    if (OnPropertyChanged != null)
                    {
                        OnPropertyChanged(property, message.Value);
                    }
                }
            }
        }

        private void SetDeviceStreamEnable(bool enable)
        {

            var m = new SDRconnectWebSocketMessage();

            m.Value = enable ? "true" : "false";            
            m.Type = SDRconnectWebSocketMessage.MessageType.DeviceStreamEnable;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        private void SetAudioStreamEnable(bool enable)
        {

            var m = new SDRconnectWebSocketMessage();

            m.Value = enable? "true" : "false";
            m.Type = SDRconnectWebSocketMessage.MessageType.AudioStreamEnable;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        private void SetIqStreamEnable(bool enable)
        {

            var m = new SDRconnectWebSocketMessage();

            m.Value = enable ? "true" : "false";
            m.Type = SDRconnectWebSocketMessage.MessageType.IqStreamEnable;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        private void SetSpectrumEnable(bool enable)
        {

            var m = new SDRconnectWebSocketMessage();

            m.Value = enable ? "true" : "false";
            m.Type = SDRconnectWebSocketMessage.MessageType.SpectrumEnable;

            var json = SDRconnectWebSocketMessage.ToJson(m);
            _client.Send(json);
        }

        #endregion
    }
}
