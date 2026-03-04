
using SDRconnectWebSocketAPI.Client;

class Program
{
    static void Main(string[] args)
    {
        var c = new SDRconnectWebSocketClient("127.0.0.1");

        c.OnConnected += () =>
        {
            Console.WriteLine("[Connected]");
            
            c.GetProperty(SDRconnectProperty.audio_volume_percent);                        
        };

        c.OnDisconnected += () =>
        {
            Console.WriteLine("[Disconnected]");
        };

        c.OnPropertyChanged += (SDRconnectProperty property, string value) =>
        {
            Console.WriteLine("[Property Changed] Property = {0} Value = {1}", property.ToString(), value);
        };

        try
        {
            c.Start();
        }
        catch
        {
            Console.WriteLine("Failed to connect");
            return;
        }

        Console.WriteLine("Press enter to exit");
        Console.ReadLine();

        c.Stop();
    }
}