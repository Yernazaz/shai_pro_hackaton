import spacy
nlp = spacy.load("ru_core_news_lg")
doc = nlp("Привет, как дела?")
for token in doc:
    print(token.text, token.pos_, token.dep_)
