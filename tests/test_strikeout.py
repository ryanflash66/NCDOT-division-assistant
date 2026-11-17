from rag.strikeout import unstrike, vocabulary

# Plain text layers as pymupdf reads them for the pages these lines came from.
CHAPTER_5_P16 = "Mowing Operation\nMultilane Divided Facilities\nSpeed: 55 MPH and Below\nVolume: Any Volume"
FHWA_COVER = "U.S. Department of Transportation\nFederal Highway Administration"


def test_words_split_by_false_strikeout_are_rejoined_as_the_page_has_them():
    # Locked wztc-047: the speed limit read as "5 5 MPH".
    assert unstrike("Speed: ~~5~~ 5 MPH and Below", CHAPTER_5_P16) == "Speed: 55 MPH and Below"
    assert unstrike("Mo ~~w~~ ing Operat ~~i~~ on   Mul ~~t~~ ilane ~~D~~ i ~~v~~ ided F ~~ac~~ i ~~l~~ it ~~i~~ es",
                    CHAPTER_5_P16) == "Mowing Operation   Multilane Divided Facilities"
    assert unstrike("U. ~~S~~ . Department of Transportation Federal H ~~ig~~ hway Ad ~~mini~~ stra ~~ti~~ on",
                    FHWA_COVER) == "U.S. Department of Transportation Federal Highway Administration"


def test_real_spaces_marks_inside_words_and_styles():
    page = "would become a permanent system. A work zone ITS deployment\nFIGURE 1\nTMP Monitoring 8"
    assert unstrike("become a ~~permanent system.~~   A work", page) == "become a permanent system.   A work"
    assert unstrike("|FIGU~~R~~E 1 |", page) == "|FIGURE 1 |"
    assert unstrike("**~~TMP Monitoring~~** **~~8~~**", page) == "**TMP Monitoring** **8**"
    # Without a text layer the marks still go; the pieces stay apart.
    assert unstrike("Speed: ~~5~~ 5 MPH", "") == "Speed: 5 5 MPH"
    assert unstrike("no marks | here", "") == "no marks | here"


def test_a_scanned_page_rejoins_pieces_into_the_documents_own_words():
    # wzi_guide p.58 is OCR'd: no text layer to ask, so the document's unmarked lines decide.
    words = vocabulary(["Figure 4.2 shows the identification of work zone impacts during planning.",
                        "Activities in a permanent system", "~~ent~~ marked lines add nothing"])
    assert "ent" not in words
    line = "Plan ~~ni~~ ng: Steps ~~in~~ F ~~ig~~ ure 4.2, acti ~~v~~ i ~~t~~ i ~~e~~ s du ~~ri~~ ng the ~~id~~ ent ~~ifi~~ cat ~~io~~ n"
    assert unstrike(line, "", words) == "Planning: Steps in Figure 4.2, activities during the identification"
    # Two known words stay two; a piece that is no word on any reading keeps its space.
    assert unstrike("become a ~~permanent~~ system", "", words) == "become a permanent system"
    assert unstrike("the ~~xq~~ zz", "", words) == "the xq zz"
