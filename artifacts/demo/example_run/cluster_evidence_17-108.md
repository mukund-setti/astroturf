# Coordinated Comment Campaign Evidence Report: 17-108

## Reviewer Executive Summary

This report summarizes the coordinated comment campaigns identified by our multi-agent Medallion Lakehouse.
Unlike naive exact-duplicate keyword detectors, our pipeline leverages deep learning embeddings to group close semantic paraphrases of the same core political template.

### Run Scope Details
- **Docket ID**: `17-108`
- **Embedding Model**: `BAAI/bge-large-en-v1.5`
- **Similarity Threshold**: `0.92`
- **Total Surfaced Clusters**: `3`
- **Total Surfaced Campaign Filings**: `1017`

---

## Surfaced Campaigns Summary Table

| Rank | Cluster ID | Size | Classification | Exact-Match % | Mean Similarity | Peak Filing Hour | Earliest Timestamp |
| --- | --- | --- | --- | --- | --- | --- | --- |
| #1 | `96413d57e367` | **1002** | `embedding/paraphrase-driven` | 1.6% | 0.9424 | `19:00 - 19:59` | 2017-08-28 |
| #2 | `753fb0e2d898` | **13** | `exact-duplicate-driven` | 100.0% | 1.0000 | `19:00 - 19:59` | 2017-08-28 |
| #3 | `73c8d60afb00` | **2** | `exact-duplicate-driven` | 100.0% | 1.0000 | `19:00 - 19:59` | 2017-08-28 |

---

## Detailed Campaign Evidentiary Packets

### Campaign #1: Cluster `96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c`

#### Campaign Profile
- **Cluster Size**: 1002 comments
- **Representative Comment ID**: `10828445130115`
- **Unique Text Hashes**: 992 (Ratio of unique texts: `0.990`)
- **Exact Match Ratio (Literal Duplicates)**: `0.016` (Proportion of members sharing an exact copy-pasted body)
- **Near-Duplicate Ratio (Paraphrased)**: `0.984` (Proportion of members who submitted customized or paraphrased text)
- **Filing Window**: `2017-08-28 17:00:02 UTC` to `2017-08-28 19:00:02 UTC`
- **Peak Hour of Activity**: `19:00 - 19:59`
- **Coordinated Style Classification**: `embedding/paraphrase-driven`

#### Semantic Similarity Profile
- **Mean Cosine Similarity to Medoid**: `0.942441`
- **Minimum Cosine Similarity in Cluster**: `0.835823`
- **Maximum Cosine Similarity in Cluster**: `1.000000`

#### Representative Campaign Template Text (Medoid)

> We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. 

The FCC should reject Chairman Ajit Pai’s proposal to hand the government-subsidized telecom giants like AT&T, Verizon, and Comcast free rein to create Internet fast lanes, stripping Internet users of the necessary privacy and access rules we demanded and just recently won. 

I’m afraid of a “pay-to-play” Internet where ISPs can charge more for certain websites because ISPs could have too much power to determine what I can do online. Thankfully, the existing net neutrality rules mean that Internet providers can’t slow or block customers’ ability to see certain web services or create Internet “fast lanes” by charging online services and websites more money to reach customers faster. That’s exactly the right balance to make sure competition in the Internet space is fair and benefits consumers and small businesses as well as larger players. Pai’s proposed repeal of the rules would transform ISPs into gatekeepers with an effective veto right on expression and innovation. That’s contrary to the basic precepts on which the Internet was built. 

It Means Everything to me. 

Thank you for keeping Title II net neutrality rules in place to protect Internet users like me.

#### Sample Campaign Comment Customizations
Below are three sample comments illustrating how different citizens customized the template:

**Sample Comment A.1 (ID: `108282535307158` | Similarity: `0.9903`)**
> We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. 

The FCC should reject Chairman Ajit Pai’s plan to hand the government-subsidized ISP monopolies like Verizon, Comcast, and AT&T the legal cover to create Internet fast lanes, stripping consumers of the meaningful access and privacy protections we demanded and won just two years ago. 

I’m afraid of a “pay-to-play” Internet where ISPs can charge more for certain websites because ISPs could have too much power to determine what I can do online. Thankfully, the current FCC regulations ensure that Internet providers can’t slow or block users’ access to certain web services or create Internet “fast lanes” by charging online services and websites money to reach customers faster. That’s exactly the right balance to make sure competition in the Internet space is fair and benefits small businesses and Internet users as well as larger players. Pai’s proposed repeal of the rules would help turn Internet providers into Internet gatekeepers with the ability to veto new innovation and expression. That’s not the kind of Internet we want to pass on to future generations of technology users. 

I grew up with our internet and throughout my time I have had great times with our internet on a variety of sites and this new plan could take away things that make the internet what it really is. A free network connecting millions. 

Thank you for keeping Title II net neutrality rules in place to protect Internet users like me.

**Sample Comment A.2 (ID: `1082893935836` | Similarity: `0.9839`)**
> We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. 

The FCC should reject Chairman Ajit Pai’s proposal to hand the government-subsidized ISP monopolies like Comcast, Verizon, and AT&T free rein to engage in data discrimination, stripping users of the necessary privacy and access safeguards we worked for and so recently won. 

I’m worried about creating a tiered Internet with “fast lanes” for certain sites or services because ISPs could have too much power to determine what I can do online. Thankfully, the existing Open Internet rules mean that ISPs can’t slow or block our access to certain web services or create Internet “fast lanes” by charging websites and online services money to reach consumers faster. That’s exactly the right balance to ensure the Internet remains a level playing field that benefits consumers and small businesses as well as entrenched Internet companies. Chairman Pai’s proposed repeal of the rules would help turn ISPs into Internet gatekeepers with the ability to veto new expression and innovation. That’s not the kind of Internet we want to pass on to future generations of technology users. 

I appreciate you maintaining Title II net neutrality rules and the rights of Internet users like me.

**Sample Comment A.3 (ID: `108280080014462` | Similarity: `0.9831`)**
> We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. 

The FCC should reject Chairman Ajit Pai’s proposal to give the ISP monopolies like Comcast, Verizon, and AT&T free rein to engage in data discrimination, stripping consumers of the meaningful privacy and access safeguards we worked for and won just two years ago. 

I’m afraid of a “pay-to-play” Internet where ISPs can charge more for certain websites because ISPs could have too much power to determine what I can do online. Thankfully, the current Open Internet rules mean that ISP monopolies can’t slow or block our access to certain web services or create Internet “fast lanes” by charging websites and online services more money to reach people faster. That’s exactly the right balance to ensure the Internet remains a level playing field that benefits consumers and small businesses as well as larger players. Pai’s proposed repeal of the rules would help turn Internet providers into Internet gatekeepers with the ability to veto new expression and innovation. That’s contrary to the basic precepts on which the Internet was built. 

The internet belongs to everyone. 

Thanks for protecting Internet users like me by upholding the existing Title II net neutrality rules.


---

### Campaign #2: Cluster `753fb0e2d898c0f0d1dbd7070b6e1fcb1a839da537e2e757b238cba2d3b75906`

#### Campaign Profile
- **Cluster Size**: 13 comments
- **Representative Comment ID**: `10828063717964`
- **Unique Text Hashes**: 1 (Ratio of unique texts: `0.077`)
- **Exact Match Ratio (Literal Duplicates)**: `1.000` (Proportion of members sharing an exact copy-pasted body)
- **Near-Duplicate Ratio (Paraphrased)**: `0.000` (Proportion of members who submitted customized or paraphrased text)
- **Filing Window**: `2017-08-28 19:00:02 UTC` to `2017-08-28 19:00:02 UTC`
- **Peak Hour of Activity**: `19:00 - 19:59`
- **Coordinated Style Classification**: `exact-duplicate-driven`

#### Semantic Similarity Profile
- **Mean Cosine Similarity to Medoid**: `1.000000`
- **Minimum Cosine Similarity in Cluster**: `1.000000`
- **Maximum Cosine Similarity in Cluster**: `1.000000`

#### Representative Campaign Template Text (Medoid)

> Net neutrality has created an unreliable landscape for consumers and businesses alike. We need Congress to bring clarity to this debate.  

#### Sample Campaign Comment Customizations
Below are three sample comments illustrating how different citizens customized the template:

**Sample Comment A.1 (ID: `108280718318885` | Similarity: `1.0000`)**
> Net neutrality has created an unreliable landscape for consumers and businesses alike. We need Congress to bring clarity to this debate.  

**Sample Comment A.2 (ID: `108280758501916` | Similarity: `1.0000`)**
> Net neutrality has created an unreliable landscape for consumers and businesses alike. We need Congress to bring clarity to this debate.  

**Sample Comment A.3 (ID: `108281221310881` | Similarity: `1.0000`)**
> Net neutrality has created an unreliable landscape for consumers and businesses alike. We need Congress to bring clarity to this debate.  


---

### Campaign #3: Cluster `73c8d60afb009ba76673e9218d60f0ef0ebaa39f421de2f1bc24040a4aeaedb3`

#### Campaign Profile
- **Cluster Size**: 2 comments
- **Representative Comment ID**: `108282615031038`
- **Unique Text Hashes**: 1 (Ratio of unique texts: `0.500`)
- **Exact Match Ratio (Literal Duplicates)**: `1.000` (Proportion of members sharing an exact copy-pasted body)
- **Near-Duplicate Ratio (Paraphrased)**: `0.000` (Proportion of members who submitted customized or paraphrased text)
- **Filing Window**: `2017-08-28 19:00:02 UTC` to `2017-08-28 19:00:02 UTC`
- **Peak Hour of Activity**: `19:00 - 19:59`
- **Coordinated Style Classification**: `exact-duplicate-driven`

#### Semantic Similarity Profile
- **Mean Cosine Similarity to Medoid**: `1.000000`
- **Minimum Cosine Similarity in Cluster**: `1.000000`
- **Maximum Cosine Similarity in Cluster**: `1.000000`

#### Representative Campaign Template Text (Medoid)

> I urge FCC Chairman Ajit Pai to preserve real Net Neutrality under the FCC’s existing rules and keep broadband internet access classified under Title II.

#### Sample Campaign Comment Customizations
Below are three sample comments illustrating how different citizens customized the template:

**Sample Comment A.1 (ID: `108282763324605` | Similarity: `1.0000`)**
> I urge FCC Chairman Ajit Pai to preserve real Net Neutrality under the FCC’s existing rules and keep broadband internet access classified under Title II.


---
