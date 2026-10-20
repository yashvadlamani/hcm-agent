# Policy RAG source

`lookup_policy` indexes the PDF `sbc-gpsd69bceiilo-il-2025.pdf` directly with LangChain's
`PyPDFLoader` and `RecursiveCharacterTextSplitter` (1,400-character chunks with 200-character
overlap), then stores local FastEmbed embeddings in Chroma. No manifest is used.

Rebuild the index after replacing/updating the PDF with `clara-policy-index --rebuild`. The default
vector-store location is `data/vectorstore/plan-policy`; set `CLARA_POLICY_VECTOR_DIR` to
change it. The answering model should cite the retrieved source page and must not infer content that
is absent from the PDF. The application does not establish whether the document has been reviewed
or approved by the plan owner.
