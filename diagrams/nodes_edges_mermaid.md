flowchart TD
subgraph Sources
M[Metadata: parent_asin title price avg_rating rating_number categories details Brand etc bought_together]
R[Reviews: user_id asin parent_asin rating text timestamp verified_purchase helpful_vote]
end

subgraph Nodes
PP[ParentProduct]
V[Variant]
U[User]
REV[Review]
B[Brand]
CAT[Category]
ATTR[Attribute]
PR[PriceRange]
CPS[CoPurchaseSet]
end

%% Metadata -> ParentProduct
M --> PP
M --> B
M --> ATTR
M --> CAT
M --> PR
M --> CPS

PP -->|HAS_BRAND| B
PP -->|HAS_ATTRIBUTE| ATTR
PP -->|BELONGS_TO_CATEGORY| CAT
PP -->|IN_PRICE_RANGE| PR
PP -->|MEMBER_OF_SET| CPS
CPS -->|HAS_ROOT| PP
PP -->|BOUGHT_TOGETHER parent_to_parent| PP

%% Reviews -> Variant + Review
R --> V
R --> REV
U -.->|WROTE| REV

%% ABOUT_PRODUCT routing
REV -->|ABOUT_PRODUCT when asin != parent_asin| V
REV -->|ABOUT_PRODUCT when asin == parent_asin| PP

%% Rating edges
U -->|RATED when asin != parent_asin| V
U -->|RATED when asin == parent_asin| PP

%% Variant to Parent
V -->|IS_VARIANT_OF| PP
