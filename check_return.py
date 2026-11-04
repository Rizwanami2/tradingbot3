with open(r'C:/Users/drxsa/OneDrive/Documents/lol/conversation_archive/tradingbot3/risk_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()
    idx = content.find('"valid": True')
    if idx >= 0:
        end_idx = content.find('}', idx)
        if end_idx >= 0:
            end_idx = content.find('}', end_idx + 1)
            if end_idx >= 0:
                end_idx = content.find('}', end_idx + 1)
                if end_idx >= 0:
                    old_return = content[idx:end_idx+1]
                    print('Found return statement:')
                    print(repr(old_return[:200]))