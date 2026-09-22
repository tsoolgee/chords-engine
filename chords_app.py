"""נקודת הכניסה של ה-EXE."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from chords_engine.desktop import main
    main()
