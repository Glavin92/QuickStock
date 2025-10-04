import speech_recognition as sr

r = sr.Recognizer()
with sr.AudioFile("C:/Users/Glavin\Documents/sem7/test_audio_files/test_restock_3.wav") as source:
    audio = r.record(source)
    text = r.recognize_google(audio)
    print(text)