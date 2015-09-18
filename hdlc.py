def encode_data(data):
    HDLC_FRAME_START = 0x7e
    HDLC_ESCAPE = 0x7d
    HDLC_ESCAPE_MASK = 0x20
    result = [HDLC_FRAME_START]
    for b in data:
        if b == HDLC_FRAME_START or b == HDLC_ESCAPE:
            result.append(HDLC_ESCAPE)
            b ^= HDLC_ESCAPE_MASK
        result.append(b)
    result.append(HDLC_FRAME_START)
    return result

def get_context():
    return dict(escape=False, waiting=True, frame=[])

def decode_data_streaming(context, s):
    HDLC_FRAME_START = 0x7e
    HDLC_ESCAPE = 0x7d
    HDLC_ESCAPE_MASK = 0x20
    while True:
        data = s.read(1)
        if len(data) == 0:
            break
        for b in data:
            i = ord(b)
            if i == HDLC_FRAME_START:
                # start new frame
                if len(context['frame']) > 0:
                    return context['frame']
                context['frame'] = []
                context['waiting'] = False
            elif i == HDLC_ESCAPE:
                if context['escape']:
                    # invalid sequence
                    context['waiting'] = True
                    context['escape'] = False
                else:
                    # next character must be un-escaped
                    context['escape'] = True
            else:
                if context['escape']:
                    # un-escape character
                    i |= HDLC_ESCAPE_MASK
                    context['escape'] = False

                if not context['waiting']:
                    # store frame byte
                    context['frame'].append(i)
    return None


def decode_stream(s, callback):
    context = get_context();
    while True:
        result = decode_data_streaming(context, s);
        if result:
            callback(result)
            context = get_context()
