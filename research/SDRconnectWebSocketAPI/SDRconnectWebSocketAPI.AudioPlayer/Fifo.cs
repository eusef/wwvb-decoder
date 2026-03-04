using System.Collections.Concurrent;

namespace SDRconnectWebSocketAPI.AudioPlayer
{
    public class Fifo
    {
        private readonly int _bufferSize;
        private readonly int _maxLength;

        private short[]? _currentBuffer;
        private int _currentBufferPos;

        private readonly ConcurrentQueue<short[]> _queue;

        public Fifo(int size, int maxLength = 0)
        {
            _queue = new ConcurrentQueue<short[]>();
            _bufferSize = size;
            _maxLength = maxLength;
        }

        public int BufferSize
        {
            get => _bufferSize;
        }

        public void Reset()
        {
            _queue.Clear();
            _currentBuffer = null;
            _currentBufferPos = 0;
        }

        public void Write(short[] data, int length)
        {
            if(_currentBuffer == null)
            {
                _currentBuffer = new short[_bufferSize];
                _currentBufferPos = 0;
            }

            var inputPosition = 0;

            while(length > 0)
            {
                var c = Math.Min(_currentBuffer.Length - _currentBufferPos, length);

                Array.Copy(data, inputPosition, _currentBuffer, _currentBufferPos, c);

                inputPosition += c;
                length -= c;
                _currentBufferPos += c;

                if(_currentBufferPos >= _bufferSize)
                {
                    if(_maxLength > 0 && _queue.Count >= _maxLength)
                    {
                        _queue.TryDequeue(out var result);
                    }
                    
                    _queue.Enqueue(_currentBuffer);
                    _currentBuffer = new short[_bufferSize];
                    _currentBufferPos = 0;
                }
            }
        }

        public bool GetBuffer(out short[] output)
        {
            if(_queue.TryDequeue(out output))
            {
                return true;
            }

            return false;
        }
    }
}
