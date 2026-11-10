OPS = {
"definition_create": """mutation CreateDef($definition: MetafieldDefinitionInput!) {
  metafieldDefinitionCreate(definition: $definition) {
    createdDefinition { id name namespace key type { name } }
    userErrors { field message code }
  }
}""",
"metafields_set": """mutation SetMF($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id namespace key }
    userErrors { field message code }
  }
}""",
"themes_list": """query { themes(first: 10) { edges { node { id name role } } } }""",
"theme_files": """query ThemeFiles($id: ID!, $filenames: [String!]!) {
  theme(id: $id) { id name files(filenames: $filenames) { nodes { filename body { ... on OnlineStoreThemeFileBodyText { content } } } } }
}""",
"theme_duplicate": """mutation Dup($id: ID!, $name: String) {
  themeDuplicate(id: $id, name: $name) {
    newTheme { id name role }
    userErrors { field message code }
  }
}""",
"theme_files_upsert": """mutation Upsert($themeId: ID!, $files: [OnlineStoreThemeFilesUpsertFileInput!]!) {
  themeFilesUpsert(themeId: $themeId, files: $files) {
    upsertedThemeFiles { filename }
    userErrors { field message code }
  }
}""",
"page_create": """mutation PageCreate($page: PageCreateInput!) {
  pageCreate(page: $page) {
    page { id title handle templateSuffix }
    userErrors { field message code }
  }
}""",
}
