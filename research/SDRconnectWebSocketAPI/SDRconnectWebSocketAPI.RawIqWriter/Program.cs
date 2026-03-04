using SDRconnectWebSocketAPI.Client;

class Program
{   
    private static SDRconnectWebSocketClient? _client;
    private static FileStream? _outputStream;
    private static BinaryWriter? _writer;
    private static ulong _totalWritten;
    
    static void Main(string[] args)
    {
        _client = new SDRconnectWebSocketClient("127.0.0.1");
        
        _client.OnConnected += () => {
            Console.WriteLine("Client connected");

            if (_client != null)
            {
                _client.IqStreamEnabled = true;
            }
        };

        _client.OnIqReceived += (short[] iq) => {
            if (_outputStream == null)
            {
                try
                {
                    _outputStream = new FileStream(@".\test_iq.raw", FileMode.Create);
                    _writer = new BinaryWriter(_outputStream);
                }
                catch
                {

                }
            }

            if (_writer != null)
            {
                foreach (var val in iq)
                {
                    _writer.Write(val);
                }

                _totalWritten += (ulong)(iq.Length * 2);
                Console.WriteLine("Wrote {0} bytes [Press Enter to stop]", _totalWritten);
            }           
        };

        try
        {
            _client.Start();
        }
        catch(Exception e)
        {
            Console.WriteLine("Failed to connect");
            return;
        }

        Console.ReadLine();
        
        _client.Stop();
        if(_outputStream != null)
        {
            _outputStream.Flush();
            _outputStream.Close();
        }
    }
};