try:
    import stegano
    from stegano import lsb
    print("ok", stegano.__file__)
except Exception as e:
    print("err", e)
